# -*- coding: utf-8 -*-
"""
rclone_g2g_copy / logic.py

원본 스크립트(g2g.py)의 rclone_server_side_copy() 로직을
"한 번 실행하고 콘솔에 print"에서 "백그라운드 스레드로 실행하고 job 상태를
파일에 기록 -> 프론트가 폴링"으로 이식한 것입니다.

!! 중요: 왜 메모리(dict)가 아니라 파일에 저장하는가 !!
처음엔 모듈 전역 dict(JOBS)에 job 상태를 들고 있었는데, 화면을 새로고침하면
방금까지 보이던 진행 상황이 사라지는 문제가 있었습니다. 원인은 ridi_book
작업 때도 확인됐던 것과 동일합니다: 이 프레임워크는 요청마다 플러그인
모듈/인스턴스를 새로 만드는 것으로 보이고, 그러면 새 요청은 완전히 새
모듈 전역(빈 JOBS dict)을 보게 됩니다. 반면 이미 시작된 백그라운드 스레드는
자신이 캡처한 "예전" 모듈 전역에 계속 값을 쓰고 있어서, 실제 rclone 프로세스는
잘 돌고 있는데 새로고침한 화면에서는 안 보이는 상황이 발생합니다.

그래서 job 상태(job_state.json)와 로그(job.log)를 **파일**에 저장합니다.
파일 경로는 어떤 모듈 인스턴스에서 봐도 항상 같으므로, 새로고침이 어느
인스턴스로 요청을 보내든 항상 같은 최신 상태를 읽습니다.

저장 위치는 요청하신 대로 앱 작업 디렉터리(cwd) 기준
./plugins/data/rclone_g2g_copy/ 를 사용합니다 (plugins/metadata/rclone_g2g_copy/
= 코드, 업데이트 시 통째로 교체됨; ./plugins/data/rclone_g2g_copy/ = 데이터,
업데이트해도 보존됨 - google_links 플러그인에서 확인된 것과 동일한 관례).

중단(취소) 기능도 같은 이유로, 파이썬 객체(Popen 인스턴스) 참조가 아니라
OS가 보장하는 값인 PID를 파일에 저장해두고 os.kill(pid, SIGTERM)으로
직접 종료합니다 - 요청을 처리하는 모듈 인스턴스가 job을 시작했던 그
인스턴스와 달라도 항상 동작합니다.

변경 이력(이번 수정, v2.35.0 — Windows 크래시 핫픽스): **rclone_g2g_copy가 실행
중이면 몇 초 안에 BookOasis 전체가 강제 종료되는 심각한 버그를 고쳤습니다**
(Windows에서 실행할 때만 발생). 원인: `_process_is_alive()`가 프로세스 생존
확인에 POSIX 관용구 `os.kill(pid, 0)`을 썼는데, Windows API에서는 시그널
번호 0이 `CTRL_C_EVENT`와 정확히 같은 값이라 이 호출이 실제로는 "그 콘솔에
붙어있는 모든 프로세스에 Ctrl+C 이벤트를 전파"하는 동작(`GenerateConsoleCtrlEvent`)
으로 해석됩니다. rclone 하위 프로세스를 별도 프로세스 그룹 없이 띄우고
있었기 때문에 BookOasis 자신의 콘솔 프로세스까지 그 이벤트를 그대로 받아
종료됩니다. 이 함수는 job이 "실행 중"인 동안 프론트엔드가 몇 초마다
폴링할 때마다(`get_last_job_status()` 경유) 호출되므로, 폴더/파일/폴더 일괄
압축해제 중 어떤 모드든 job을 시작하기만 하면 다음 폴링에서 거의 확정적으로
재현됐습니다. 수정 내용:
- `_process_is_alive()`를 Windows에서는 `ctypes`로 `OpenProcess`+
  `GetExitCodeProcess`를 직접 호출해 생존 여부만 안전하게 확인하도록
  분기했습니다(POSIX는 기존 `os.kill(pid, 0)` 그대로 유지).
- `signal.SIGKILL`은 Windows의 `signal` 모듈에 아예 없는 속성이라(참조 시
  `AttributeError`) 강제 종료 폴백 시 `getattr(signal, "SIGKILL",
  signal.SIGTERM)`으로 안전하게 대체했습니다.
- 방어적으로, 모든 rclone `subprocess.Popen`/`subprocess.run` 호출에
  Windows에서는 `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`,
  POSIX에서는 `start_new_session=True`를 적용해 하위 프로세스를 부모
  콘솔/프로세스 그룹과 분리했습니다 - 앞으로 비슷한 종류의 신호 관련
  문제가 생겨도 BookOasis 본체까지 전파되지 않도록 하는 안전장치입니다.
- `folder_extract` 모드의 목적지 절대경로 검증을 POSIX 전용이던
  `dest_folder_name.startswith("/")`에서 `os.path.isabs(dest_folder_name)`로
  바꿔, Windows 드라이브 경로(`K:\다운로드`, `K:/다운로드` 등)도 정상적으로
  절대경로로 인식하도록 했습니다(이전에는 Windows 경로가 전부
  ValueError로 거부됐습니다).

변경 이력(v2.34.0): "다운로드 후 압축 해제(folder_extract)" 모드를 추가했습니다.
개별 파일을 rclone backend copyid로 서버 로컬 스테이징 폴더에 내려받은 뒤,
파이썬 표준 라이브러리 zipfile로 최종 목적지(로컬 절대경로)에 압축을 풉니다
(zip/cbz만 지원 - rar 등은 미지원). 압축 해제는 rclone이 할 수 있는 일이
아니라서 다운로드까지만 rclone(subprocess)에 맡기고, 그 다음 단계는 순수
파이썬으로 처리합니다. 자세한 것은 아래 "다운로드 후 압축 해제" 절 참고.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import ctypes
import threading
import time
import urllib.request
import uuid
import zipfile
from configparser import ConfigParser

PLUGIN_ID = "rclone_g2g_copy"

# 앱 실행 작업 디렉터리(cwd) 기준 상대 경로. __file__ 기준 상위 폴더를
# 거슬러 올라가는 대신, 요청하신 대로 "./plugins/data/<플러그인id>"를
# 그대로 사용한다 (google_links 플러그인에서 확인된 것과 동일한 상대 경로
# 표기 관례).
DATA_DIR = os.path.join(".", "plugins", "data", PLUGIN_ID)  # ./plugins/data/rclone_g2g_copy
STATE_FILE = os.path.join(DATA_DIR, "job_state.json")
LOG_FILE = os.path.join(DATA_DIR, "job.log")

# 폴링 응답으로 돌려주는 최대 라인 수. 화면 전환/새로고침 직후 첫 폴링에서
# 이 값만큼을 통째로 내려받아 렌더링하므로, 너무 크면 전송량과 렌더링 둘 다
# 느려진다. 최근 상황만 보이면 충분하다는 전제로 낮춰뒀다 - 전체 로그는
# 여전히 job.log 파일에 다 남아있으니 필요하면 서버에서 직접 확인 가능.
_MAX_RETURN_LINES = 30

# 같은 프로세스 안에서의 파일 read-modify-write 경합만 막는 용도(여러 워커/
# 프로세스 간 완전한 동시성 보장은 아님 - 1워커 전제와 동일한 수준의 안전성)
_STATE_LOCK = threading.Lock()

# rclone --progress 출력에서 진행률을 뽑아내는 정규식.
# rclone은 --progress 상태 블록에 "Transferred:" 줄을 두 개 찍는다 -
# 하나는 바이트 기준(용량/속도/ETA 포함), 하나는 파일 개수 기준. 예:
#   Transferred:       340.471 MiB / 1.818 GiB, 18%, 3.410 MiB/s, ETA 7m26s
#   Transferred:            9 / 8053, 0%
_BYTE_PROGRESS_RE = re.compile(
    r"^Transferred:\s*([\d.]+\s*[A-Za-z]+)\s*/\s*([\d.]+\s*[A-Za-z]+),\s*(\d+)%,"
    r"\s*([\d.]+\s*[A-Za-z]+/s),\s*ETA\s+(.+?)\s*$"
)
_FILES_PROGRESS_RE = re.compile(r"^Transferred:\s*(\d+)\s*/\s*(\d+),\s*(\d+)%\s*$")


def _parse_progress_line(line):
    """rclone --progress 출력 한 줄에서 진행률 정보를 뽑아낸다.

    매치되면 dict(일부 키만 채워짐), 아니면 None을 반환한다.

    rclone은 두 "Transferred:" 줄 각각에 자기 나름의 퍼센트를 찍는다 - 바이트
    기준 퍼센트(전체 용량 대비)와 파일 개수 기준 퍼센트(전체 개수 대비)는
    파일 크기가 제각각이면 서로 다르게 움직일 수 있다. 서버사이드 복사에서는
    바이트 기준 줄보다 파일 개수 기준 줄이 더 자주/먼저 갱신되는 경우가 있어,
    "전체 진행률"이 잘 안 움직이는 것처럼 보일 수 있다는 점을 감안해 둘 다
    각각의 키로 보존한다 (프론트에서 바이트 기준을 우선하고 없으면 파일 개수
    기준으로 대체)."""
    line = line.strip()

    m = _BYTE_PROGRESS_RE.match(line)
    if m:
        return {
            "percent": int(m.group(3)),
            "transferred": m.group(1).strip(),
            "total": m.group(2).strip(),
            "speed": m.group(4).strip(),
            "eta": m.group(5).strip(),
        }

    m = _FILES_PROGRESS_RE.match(line)
    if m:
        return {
            "files_done": int(m.group(1)),
            "files_total": int(m.group(2)),
            "files_percent": int(m.group(3)),
        }

    return None


class ConfigError(Exception):
    """RCLONE_PATH / CONFIG_PATH 가 잘못 설정되었을 때"""


def get_folder_id(drive_url):
    """구글 드라이브 URL에서 폴더 ID를 추출합니다. (원본 g2g.py와 동일 로직)"""
    match = re.search(r"folders/([a-zA-Z0-9-_]+)", drive_url)
    if match:
        return match.group(1)
    drive_url = (drive_url or "").strip()
    if drive_url and "/" not in drive_url:
        return drive_url
    raise ValueError("유효한 구글 드라이브 폴더 주소가 아닙니다.")


def get_file_id(drive_url):
    """구글 드라이브 개별 파일(zip/cbz 등 압축파일 1개) URL에서 파일 ID를 추출합니다.

    지원 패턴:
      - https://drive.google.com/file/d/<ID>/view?usp=sharing
      - https://drive.google.com/open?id=<ID>
      - https://drive.google.com/uc?id=<ID>&export=download
      - 슬래시가 없는 순수 파일 ID 문자열을 그대로 입력한 경우
    """
    drive_url = (drive_url or "").strip()
    match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", drive_url)
    if match:
        return match.group(1)
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", drive_url)
    if match:
        return match.group(1)
    if drive_url and "/" not in drive_url:
        return drive_url
    raise ValueError("유효한 구글 드라이브 파일 주소가 아닙니다.")


def list_rclone_remotes(config_path):
    """rclone.conf 파일을 파싱해 등록된 remote 이름 목록을 반환한다.

    rclone.conf는 INI 형식이고, 각 remote는 `[remote_name]` 섹션 헤더로
    시작한다. configparser로 그대로 파싱 가능하지만, 값들 중 `%`가 포함된
    경우(예: 인코딩된 토큰 문자열) configparser의 기본 보간(interpolation)
    기능이 오류를 낼 수 있어 interpolation=None으로 끈 raw 모드를 쓴다.

    파일이 없거나 파싱에 실패하면(설정을 아직 안 끝냈거나 잘못된 경로) 예외를
    던지지 않고 빈 리스트를 반환한다 - 설정 화면 자체가 깨지면 안 되므로.
    """
    config_path = (config_path or "").strip()
    if not config_path or not os.path.exists(config_path):
        return []
    try:
        parser = ConfigParser(interpolation=None)
        parser.read(config_path, encoding="utf-8")
        return list(parser.sections())
    except Exception:
        return []


def to_rclone_relative_path(path, mount_prefix):
    """
    사용자가 도커/호스트 마운트 기준 경로(예: /mnt/zeeps_member/zeepsmember/공유폴더)를
    입력해도, rclone remote 기준 상대 경로(예: /zeepsmember/공유폴더)로 자동 변환한다.

    rclone remote가 실제로는 호스트에 /mnt/<remote명> 같은 경로로 마운트되어 있는
    경우, 사용자는 파일탐색기/터미널에서 본 마운트 경로를 그대로 붙여넣기 쉬운데,
    rclone copy의 목적지는 "remote:상대경로" 형태라 마운트 접두사가 중복으로
    들어가면 안 된다. 입력이 mount_prefix로 시작하면 그 접두사를 잘라내고,
    아니면 이미 rclone 기준 경로라고 보고 그대로 반환한다.
    """
    path = (path or "").strip()
    if not path:
        return path

    normalized_path = path.rstrip("/")
    normalized_prefix = (mount_prefix or "").strip().rstrip("/")

    if normalized_prefix and normalized_path.startswith(normalized_prefix):
        remainder = normalized_path[len(normalized_prefix):]
        if not remainder.startswith("/"):
            remainder = "/" + remainder
        return remainder or "/"

    return path


def resolve_mount_prefix(mount_prefix, rclone_remote):
    """설정에 MOUNT_PREFIX가 비어있으면 관례적인 기본값(/mnt/<remote명>)을 사용한다."""
    mount_prefix = (mount_prefix or "").strip()
    if mount_prefix:
        return mount_prefix
    rclone_remote = (rclone_remote or "").strip()
    return f"/mnt/{rclone_remote}" if rclone_remote else ""


def _validate_config(rclone_path, config_path):
    if os.path.isabs(rclone_path) or "/" in rclone_path or "\\" in rclone_path:
        if not os.path.exists(rclone_path):
            raise ConfigError(f"지정한 경로에서 rclone 실행 파일을 찾을 수 없습니다: {rclone_path}")
    if not os.path.exists(config_path):
        raise ConfigError(f"지정한 경로에서 rclone.conf 파일을 찾을 수 없습니다: {config_path}")


# ---------------------------------------------------------------------------
# 파일 기반 상태 저장
# ---------------------------------------------------------------------------

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_state(state):
    """임시 파일에 쓴 뒤 원자적으로 교체 - 폴링 중인 다른 요청이 쓰다 만
    JSON을 읽는 상황을 피한다."""
    _ensure_data_dir()
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp_path, STATE_FILE)


def _update_state(**changes):
    with _STATE_LOCK:
        state = _read_state() or {}
        state.update(changes)
        _write_state(state)
    return state


def _reset_log():
    _ensure_data_dir()
    with open(LOG_FILE, "w", encoding="utf-8"):
        pass


def _append_log_line(text):
    _ensure_data_dir()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def _read_log_lines():
    """로그 파일의 마지막 _MAX_RETURN_LINES 줄만 읽는다.

    이전에는 파일 전체를 읽은 뒤 파이썬에서 뒤쪽만 잘라냈는데, 복사가 오래
    걸려 로그가 커지면(수천~수만 줄) 매 폴링(1초 간격)마다 파일 전체를 메모리에
    올리는 게 화면 전환/새로고침 직후 느려지는 원인 중 하나였다. 파일 끝에서부터
    청크 단위로 거꾸로 읽어 필요한 줄 수만 확보하면 로그가 아무리 커져도 매번
    읽는 양이 일정하다.
    """
    try:
        file_size = os.path.getsize(LOG_FILE)
    except FileNotFoundError:
        return []

    chunk_size = 8192
    blocks = []
    lines_found = 0
    remaining = file_size

    with open(LOG_FILE, "rb") as f:
        while remaining > 0 and lines_found <= _MAX_RETURN_LINES:
            read_size = min(chunk_size, remaining)
            remaining -= read_size
            f.seek(remaining)
            block = f.read(read_size)
            blocks.append(block)
            lines_found += block.count(b"\n")

    content = b"".join(reversed(blocks)).decode("utf-8", errors="replace")
    lines = content.splitlines()
    truncated = len(lines) > _MAX_RETURN_LINES or remaining > 0
    lines = lines[-_MAX_RETURN_LINES:]
    if truncated:
        lines = ["... (앞부분 생략) ..."] + lines
    return lines


def looks_like_windows_local_path(path):
    """목적지 문자열이 (호스트 OS와 무관하게) Windows 드라이브 문자 경로
    ('K:\\...', 'K:/...') 또는 UNC 경로('\\\\서버\\공유\\...')처럼 보이는지
    판별한다.

    이 두 형태는 rclone 원격 상대경로 관례로는 절대 나오지 않으므로("원격
    이름:경로"에서 우리가 다루는 건 콜론 뒤의 경로 부분뿐이고, 그 부분이
    드라이브 문자로 시작할 일은 없다) - 이 패턴에 매치되면 사용자가 어떤
    소스 종류를 선택했든 "로컬 경로를 쓰려는 의도"로 100% 확신할 수 있다.

    반대로 POSIX 스타일 절대경로('/data/...')는 이 함수가 로컬로 판별하지
    않는다 - rclone 원격 상대경로도 흔히 '/'로 시작하는 관례를 쓰기 때문에
    (예: '/zeepsmember/폴더'), 문자열만으로는 "로컬 디스크의 그 경로"인지
    "그 원격 안의 그 경로"인지 구분할 수 없다. 이 모호한 경우는 자동 판별을
    포기하고 기존 동작(사용자가 명시적으로 고른 소스 종류를 그대로 따름)을
    유지하는 편이 안전하다 - 잘못 추측해서 로컬인 줄 알고 처리했는데
    사실은 원격 경로였다면(또는 반대) 훨씬 더 헷갈리는 오류가 난다.
    """
    if not path:
        return False
    if re.match(r"^[A-Za-z]:[\\/]", path):
        return True
    if path.startswith("\\\\"):
        return True
    return False


def _normalize_local_abs_path(path):
    """압축 해제 목적지(서버 로컬 절대경로)의 끝 구분자를 정리한다.

    POSIX('/')와 Windows('\\') 구분자를 모두 다루되, 드라이브 루트(예:
    'K:\\', '/')만 남는 경우는 그 자체를 절대경로로 유지해야 하므로
    구분자를 완전히 떼어내지 않는다 - 'K:\\'에서 그냥 rstrip하면 'K:'가
    남는데, os.path.isabs('K:')는 Windows에서도 False(드라이브 상대경로로
    취급)라 이후 처리가 깨진다.
    """
    stripped = path.rstrip("/\\")
    if not stripped:
        return path  # 루트 자체('/', 'C:\\' 등) - 원본 유지
    if os.name == "nt" and re.fullmatch(r"[A-Za-z]:", stripped):
        return stripped + "\\"
    return stripped


def _process_is_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        # !! 매우 중요 !! Windows에서는 os.kill(pid, 0)을 쓰면 안 된다.
        # POSIX에서 시그널 0은 "프로세스 존재 확인용" 관용구로 안전하지만,
        # Windows API에서는 그 값(0)이 CTRL_C_EVENT와 정확히 같아서
        # os.kill(pid, 0)이 실제로는 GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)를
        # 호출해버린다 - 이는 pid가 속한 콘솔에 연결된 "모든" 프로세스에
        # Ctrl+C를 전파한다. rclone 하위 프로세스가 부모(BookOasis)와 같은
        # 콘솔을 공유하고 있었기 때문에, 이 한 줄 때문에 BookOasis 프로세스
        # 자체가 몇 초 만에 강제 종료되는 심각한 버그가 있었다(v2.35.0에서
        # 발견/수정). 대신 OpenProcess + GetExitCodeProcess로 순수하게
        # 조회만 하는 방식을 쓴다 - 아무 신호도 보내지 않는다.
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False  # 이미 종료되었거나(대부분) 접근 권한이 없는 pid
        try:
            exit_code = ctypes.c_ulong(0)
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, TypeError):
        return False
    except OSError:
        return False
    return True


# Windows의 signal 모듈에는 SIGKILL이 아예 없다(AttributeError). SIGTERM은
# os.kill()을 통해 Windows에서도 TerminateProcess로 이어지므로(강제 종료 효과가
# 이미 있음) 이걸로 안전하게 대체한다.
_HARD_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)


# rclone 하위 프로세스를 부모(BookOasis)의 콘솔/프로세스 그룹과 분리해서
# 띄우기 위한 공용 Popen/run 인자. 위 _process_is_alive() 버그처럼 앞으로
# 비슷한 신호 관련 문제가 또 생기더라도 BookOasis 본체까지 전파되지 않도록
# 막아주는 방어적 조치다(POSIX: 새 세션, Windows: 새 프로세스 그룹).
if os.name == "nt":
    _SUBPROCESS_ISOLATION_KWARGS = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
else:
    _SUBPROCESS_ISOLATION_KWARGS = {"start_new_session": True}


def _notify_discord(webhook_url, content):
    """복사 완료/실패/중단 시 디스코드 웹훅으로 알림을 보낸다.

    표준 라이브러리(urllib)만 쓰고, 실패해도 job 진행/결과 자체에는 영향을
    주지 않도록 예외를 삼킨다 (알림 실패로 job이 죽으면 안 되므로)."""
    webhook_url = (webhook_url or "").strip()
    if not webhook_url:
        return
    try:
        body = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:  # noqa: BLE001 - 알림 실패는 조용히 로그만
        _append_log_line(f"[!] 디스코드 알림 전송 실패: {e}")


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

_CONFIG_SAVE_HINT_SHOWN = False  # 같은 job 안에서 힌트를 반복 출력하지 않기 위한 플래그


def _maybe_explain_config_save_error(line):
    """rclone이 OAuth 토큰 갱신 후 rclone.conf에 다시 저장하려다 실패하는,
    잘 알려진 rclone+Docker 이슈(rclone/rclone#6656)를 감지해 설명을 덧붙인다.

    원인: rclone.conf 파일 "하나만" 도커에 바인드 마운트하면, 그 파일 자체가
    마운트 지점이 되어 rclone이 원자적 저장을 위해 시도하는
    rename(rclone.conf -> rclone.conf.old)이 "device or resource busy"로
    실패한다. 코드로 고칠 수 있는 부분이 아니라(도커 볼륨 설정 문제),
    최소한 원인과 해결책을 로그에 바로 보여준다.
    """
    global _CONFIG_SAVE_HINT_SHOWN
    if _CONFIG_SAVE_HINT_SHOWN:
        return
    if "Failed to save config" not in line and "device or resource busy" not in line:
        return
    _CONFIG_SAVE_HINT_SHOWN = True
    _append_log_line(
        "[!] 참고: 위 오류는 이 플러그인이 아니라 rclone + Docker의 잘 알려진 "
        "이슈입니다 (rclone/rclone#6656). 구글 인증 토큰이 갱신될 때 rclone이 "
        "rclone.conf를 rename 방식으로 다시 저장하려 하는데, rclone.conf 파일을 "
        "'파일 하나만' 도커에 바인드 마운트해두면 그 rename이 불가능해서 발생합니다. "
        "docker-compose에서 rclone.conf 파일 하나만 마운트하지 말고, 그 파일이 "
        "들어있는 디렉터리 전체를 마운트하도록 바꾸면 해결됩니다. "
        "(대개 이 오류가 나도 이번 복사 자체는 계속 진행되지만, 갱신된 토큰이 "
        "저장되지 않으므로 매번 반복해서 나타날 수 있습니다.)"
    )


# ---------------------------------------------------------------------------
# 다운로드 후 압축 해제 (folder_extract 모드) 관련 헬퍼
#
# rclone은 전송(복사/이동/동기화) 전용 도구라 압축 해제 기능이 없다. 그래서
# 이 모드는 "다운로드는 rclone(backend copyid)으로, 압축 해제는 파이썬
# zipfile로"라는 2단계로 나눠서 동작한다:
#   1) rclone backend copyid로 이 job 전용 스테이징 폴더(임시 경로)에 원본
#      압축파일을 내려받는다 (구글 드라이브 -> 서버 로컬).
#   2) 다운로드가 끝나면 그 파일을 zipfile로 최종 목적지(로컬 절대경로)에
#      풀어놓고, 스테이징 폴더는 정리한다.
# ---------------------------------------------------------------------------

_SUPPORTED_ARCHIVE_EXTS = {".zip", ".cbz"}

# rclone 다운로드가 임시로 거쳐가는 스테이징 폴더 - job_state.json/job.log와
# 같은 DATA_DIR(코드와 분리된, 업데이트해도 보존되는 데이터 경로) 아래에 둔다.
_STAGING_ROOT = os.path.join(DATA_DIR, "staging")


def _staging_dir_for_job(job_id):
    return os.path.join(_STAGING_ROOT, job_id)


def _cleanup_staging_dir(staging_dir):
    """스테이징 폴더를 통째로 제거한다. 정리 실패가 job 성공/실패 판정에
    영향을 주면 안 되므로 예외를 조용히 삼킨다."""
    try:
        if staging_dir and os.path.isdir(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


def _find_single_downloaded_file(staging_dir):
    """스테이징 폴더(이 job 전용으로 새로 만든 빈 폴더) 안에 다운로드된 파일이
    정확히 1개인지 확인하고 경로를 반환한다. 0개/2개 이상이면 (None, 에러메시지)."""
    try:
        entries = [
            os.path.join(staging_dir, name)
            for name in os.listdir(staging_dir)
            if os.path.isfile(os.path.join(staging_dir, name))
        ]
    except FileNotFoundError:
        return None, "다운로드 폴더를 찾을 수 없습니다."

    if len(entries) == 0:
        return None, "다운로드된 파일을 찾을 수 없습니다 (rclone은 성공했다고 보고했지만 파일이 없습니다)."
    if len(entries) > 1:
        return None, f"다운로드 폴더에 파일이 {len(entries)}개 있어 어느 것을 압축 해제할지 알 수 없습니다."
    return entries[0], None


def _extract_archive(archive_path, dest_dir):
    """zip/cbz 압축파일 하나를 dest_dir에 풀어놓는다.

    반환: (True, 압축 해제된 항목 수) 또는 (False, 에러 메시지)

    zip slip(압축파일 안의 상대경로가 '../' 등으로 목적지 바깥을 가리키는
    공격) 방지를 위해, 실제로 풀기 전에 모든 항목의 최종 경로가 dest_dir
    내부인지 먼저 전부 검증한다.
    """
    ext = os.path.splitext(archive_path)[1].lower()
    if ext not in _SUPPORTED_ARCHIVE_EXTS and not zipfile.is_zipfile(archive_path):
        return False, (
            f"지원하지 않는 압축 형식입니다 ({ext or '확장자 없음'}). "
            "현재는 zip/cbz(zip 포맷)만 자동 압축 해제를 지원합니다."
        )

    try:
        os.makedirs(dest_dir, exist_ok=True)
        dest_real = os.path.realpath(dest_dir)
        with zipfile.ZipFile(archive_path) as zf:
            names = zf.namelist()
            for member in names:
                target_real = os.path.realpath(os.path.join(dest_dir, member))
                if target_real != dest_real and not target_real.startswith(dest_real + os.sep):
                    return False, f"압축 해제 중단: 안전하지 않은 경로가 포함되어 있습니다 ({member})"
            zf.extractall(dest_dir)
        return True, len(names)
    except zipfile.BadZipFile as e:
        return False, f"압축 해제 실패 (손상되었거나 zip 포맷이 아닌 파일일 수 있음): {e}"
    except Exception as e:  # noqa: BLE001
        return False, f"압축 해제 실패: {e}"


def _kind_label(source_kind):
    return {
        "folder": "폴더 복사",
        "folder_local": "폴더 로컬 다운로드",
        "file": "파일 복사",
        "file_local": "로컬 다운로드",
        "folder_extract": "일괄 압축 해제",
    }.get(source_kind, "복사")


def _list_archive_files_in_folder(rclone_path, config_path, rclone_remote, folder_id):
    """소스 폴더(folder_id) 안의 zip/cbz 파일들을 재귀적으로(하위 폴더 포함)
    나열한다. root_folder_id 트릭으로 그 폴더를 remote의 루트인 것처럼 가장해
    `rclone lsjson --recursive`를 호출한다 (folder 모드의 `rclone copy`가
    쓰는 트릭과 동일한 원리).

    반환: (파일 목록, None) 또는 (None, 에러 메시지)
    파일 목록의 각 항목: {"id": 파일ID, "path": 폴더 기준 상대경로, "name": 파일명, "size": 바이트수}
    ID가 없는 항목(백엔드가 ID를 안 주는 경우)은 backend copyid로 받을 수
    없으므로 조용히 건너뛴다.
    """
    source = f"{rclone_remote},root_folder_id={folder_id}:"
    cmd = [rclone_path, "lsjson", source, "--recursive", "--config", config_path]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            **_SUBPROCESS_ISOLATION_KWARGS,
        )
    except Exception as e:  # noqa: BLE001
        return None, f"폴더 목록 조회 실패: {e}"

    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
        return None, f"폴더 목록 조회 실패 (종료 코드 {result.returncode}): {stderr_text[:500]}"

    try:
        entries = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        return None, f"폴더 목록 응답 파싱 실패: {e}"

    files = []
    for entry in entries:
        if entry.get("IsDir"):
            continue
        name = entry.get("Name") or ""
        ext = os.path.splitext(name)[1].lower()
        if ext not in _SUPPORTED_ARCHIVE_EXTS:
            continue
        file_id = entry.get("ID")
        if not file_id:
            continue
        files.append({
            "id": file_id,
            "path": entry.get("Path") or name,
            "name": name,
            "size": entry.get("Size"),
        })
    # 안정적인 처리 순서(로그/디스코드 알림이 매번 같은 순서로 보이도록)
    files.sort(key=lambda f: f["path"])
    return files, None


def _run_folder_extract_job(job_id, rclone_path, config_path, rclone_remote, folder_id, dest_root_dir,
                             discord_webhook_url=None, keep_archive_after_extract=False):
    """소스 폴더(folder_id) 안의 zip/cbz 파일들을 각각 rclone backend copyid로
    내려받고 압축을 풀어, dest_root_dir(로컬 절대경로) 아래에 원본 폴더 구조를
    유지한 채 배치한다.

    예: 소스 폴더/시즌1/01권.zip -> dest_root_dir/시즌1/01권/*.jpg

    폴더/개별 파일 모드(_run_job의 나머지 부분)와 달리 rclone 프로세스 하나가
    아니라 파일 개수만큼 여러 번 실행되므로, 공통 흐름을 공유하지 않고 이
    함수 안에서 전체(목록 조회 -> 개별 다운로드 -> 개별 압축 해제 -> 정리)를
    처리한다. 파일 하나가 실패해도 나머지는 계속 진행하고, 끝에 성공/실패
    개수를 요약해서 보여준다.
    """
    global _CONFIG_SAVE_HINT_SHOWN
    _CONFIG_SAVE_HINT_SHOWN = False

    _append_log_line("=" * 60)
    _append_log_line(f"[*] Rclone 경로       : {rclone_path}")
    _append_log_line(f"[*] Config 파일 경로  : {config_path}")
    _append_log_line(f"[*] 소스 폴더 ID      : {folder_id}")
    _append_log_line(f"[*] 목적지 경로       : {dest_root_dir}")
    _append_log_line("[*] 복사 방식         : 폴더 내 압축파일 일괄 다운로드 + 압축 해제 (rclone backend copyid → zip 추출)")
    _append_log_line("=" * 60)
    _append_log_line("[*] 폴더 안의 압축파일 목록을 조회합니다...\n")

    files, list_error = _list_archive_files_in_folder(rclone_path, config_path, rclone_remote, folder_id)
    if list_error:
        _append_log_line(f"[-] {list_error}")
        _update_state(status="error", returncode=None, finished_at=time.time(), pid=None, progress={})
        _notify_discord(
            discord_webhook_url,
            f"❌ **[BookOasis] 일괄 압축 해제 실패**\n목적지: `{dest_root_dir}`\n사유: {list_error}",
        )
        return

    total = len(files)
    if total == 0:
        msg = "폴더 안(하위 폴더 포함)에서 압축 해제할 zip/cbz 파일을 찾지 못했습니다."
        _append_log_line(f"[-] {msg}")
        _update_state(status="error", returncode=None, finished_at=time.time(), pid=None, progress={})
        _notify_discord(
            discord_webhook_url,
            f"❌ **[BookOasis] 일괄 압축 해제 실패**\n목적지: `{dest_root_dir}`\n사유: {msg}",
        )
        return

    _append_log_line(f"[+] {total}개의 압축파일을 찾았습니다.\n")
    _update_state(progress={"files_done": 0, "files_total": total, "percent": 0})

    dest_root_real = os.path.realpath(dest_root_dir)
    job_staging_root = _staging_dir_for_job(job_id)
    succeeded = []
    failed = []  # [(rel_path, 에러메시지), ...]
    cancelled = False

    for idx, entry in enumerate(files, start=1):
        state = _read_state() or {}
        if bool(state.get("cancel_requested")):
            cancelled = True
            _append_log_line(f"\n[-] 사용자 요청으로 중단되었습니다. ({idx - 1}/{total}개 처리 완료)")
            break

        rel_path = entry["path"]
        file_id = entry["id"]
        _append_log_line(f"\n[*] ({idx}/{total}) 처리 중: {rel_path}")

        # 파일마다 별도의 스테이징 하위 폴더를 써서, "다운로드된 파일이
        # 정확히 1개인지" 판정이 다른 파일과 절대 섞이지 않게 한다.
        staging_dir = os.path.join(job_staging_root, str(idx))
        try:
            os.makedirs(staging_dir, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            failed.append((rel_path, f"임시 폴더 생성 실패: {e}"))
            _append_log_line(f"[-] 임시 폴더 생성 실패: {e}")
            continue

        # copyid는 목적지 경로 끝에 구분자가 있어야 "그 디렉터리 안에 원본
        # 파일명대로 저장"으로 해석한다. staging_dir은 로컬 파일시스템 경로라
        # (원격 rclone 경로와 달리) OS에 맞는 구분자를 써야 한다 - Windows에서
        # os.sep은 '\\'이므로 무조건 '/'를 붙이면 혼합 구분자가 되어버린다.
        staging_dest = staging_dir if staging_dir.endswith(os.sep) else staging_dir + os.sep
        cmd = [
            rclone_path, "backend", "copyid",
            f"{rclone_remote}:", file_id, staging_dest,
            "--config", config_path, "--progress",
        ]

        returncode = None
        file_progress = {}
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                **_SUBPROCESS_ISOLATION_KWARGS,
            )
            _update_state(pid=process.pid)

            for raw_line in process.stdout:
                try:
                    decoded = raw_line.decode("utf-8", errors="replace")
                except Exception:
                    decoded = raw_line.decode("latin-1", errors="ignore")
                decoded = decoded.rstrip("\n")
                for piece in decoded.split("\r"):
                    if piece:
                        _append_log_line(piece)
                        parsed = _parse_progress_line(piece)
                        if parsed:
                            file_progress.update(parsed)
                            file_fraction = (file_progress.get("percent") or file_progress.get("files_percent") or 0) / 100.0
                            overall_percent = int(((idx - 1) + file_fraction) / total * 100)
                            _update_state(progress={
                                "files_done": idx - 1,
                                "files_total": total,
                                "percent": overall_percent,
                                "current_file": rel_path,
                                "transferred": file_progress.get("transferred"),
                                "total": file_progress.get("total"),
                                "speed": file_progress.get("speed"),
                                "eta": file_progress.get("eta"),
                            })

            process.wait()
            returncode = process.returncode
        except Exception as e:  # noqa: BLE001
            _append_log_line(f"[-] 다운로드 중 예외 발생: {e}")

        state = _read_state() or {}
        if bool(state.get("cancel_requested")):
            cancelled = True
            _cleanup_staging_dir(staging_dir)
            _append_log_line(f"\n[-] 사용자 요청으로 중단되었습니다. ({idx - 1}/{total}개 처리 완료)")
            break

        if returncode != 0:
            failed.append((rel_path, f"다운로드 실패 (종료 코드 {returncode})"))
            _append_log_line(f"[-] 다운로드 실패 (종료 코드: {returncode})")
            _cleanup_staging_dir(staging_dir)
            continue

        staged_file, find_error = _find_single_downloaded_file(staging_dir)
        if find_error:
            failed.append((rel_path, find_error))
            _append_log_line(f"[-] {find_error}")
            _cleanup_staging_dir(staging_dir)
            continue

        # 원본 폴더 구조(하위 폴더 포함)를 유지하면서, 확장자를 뗀 이름의
        # 폴더에 압축을 푼다. 예: "시즌1/01권.zip" -> "시즌1/01권/"
        rel_no_ext = os.path.splitext(rel_path)[0]
        target_dir = os.path.normpath(os.path.join(dest_root_dir, rel_no_ext))
        target_real = os.path.realpath(target_dir)
        if target_real != dest_root_real and not target_real.startswith(dest_root_real + os.sep):
            failed.append((rel_path, "안전하지 않은 경로가 포함되어 있어 건너뜀"))
            _append_log_line(f"[-] 안전하지 않은 경로라 건너뜁니다: {rel_path}")
            _cleanup_staging_dir(staging_dir)
            continue

        ok, result = _extract_archive(staged_file, target_dir)
        if not ok:
            failed.append((rel_path, result))
            _append_log_line(f"[-] 압축 해제 실패: {result}")
            _cleanup_staging_dir(staging_dir)
            continue

        _append_log_line(f"[+] 압축 해제 완료: {target_dir} ({result}개 항목)")
        if keep_archive_after_extract:
            try:
                archive_dest = os.path.join(target_dir, os.path.basename(staged_file))
                shutil.move(staged_file, archive_dest)
            except Exception as e:  # noqa: BLE001
                _append_log_line(f"[!] 원본 압축파일 보관 실패(무시하고 계속): {e}")
        _cleanup_staging_dir(staging_dir)

        succeeded.append(rel_path)
        _update_state(progress={
            "files_done": idx,
            "files_total": total,
            "percent": int(idx / total * 100),
        })

    _cleanup_staging_dir(job_staging_root)  # 개별 파일마다 이미 정리했지만, 남은 게 있으면 마저 정리

    if cancelled:
        status = "cancelled"
        notify_text = (
            f"⏹️ **[BookOasis] 일괄 압축 해제 중단됨**\n목적지: `{dest_root_dir}`\n"
            f"완료 {len(succeeded)} / 실패 {len(failed)} / 전체 {total}"
        )
        final_progress = {"files_done": len(succeeded), "files_total": total}
    elif failed:
        status = "error"
        _append_log_line(f"\n[-] 일부 실패: 성공 {len(succeeded)}개 / 실패 {len(failed)}개 / 전체 {total}개")
        for path, err in failed:
            _append_log_line(f"    - {path}: {err}")
        notify_text = (
            f"⚠️ **[BookOasis] 일괄 압축 해제 일부 실패**\n목적지: `{dest_root_dir}`\n"
            f"성공 {len(succeeded)} / 실패 {len(failed)} / 전체 {total}"
        )
        final_progress = {"files_done": len(succeeded), "files_total": total}
    else:
        status = "success"
        _append_log_line(f"\n[+] 전체 {total}개 압축파일의 다운로드 + 압축 해제가 모두 완료되었습니다!")
        notify_text = (
            f"✅ **[BookOasis] 일괄 압축 해제 완료**\n목적지: `{dest_root_dir}`\n전체 {total}개 처리 완료"
        )
        final_progress = {"files_done": total, "files_total": total, "percent": 100}

    _update_state(status=status, returncode=None, finished_at=time.time(), pid=None, progress=final_progress)
    _notify_discord(discord_webhook_url, notify_text)


def _run_job(job_id, rclone_path, config_path, rclone_remote, source_id, dest_folder_name,
             discord_webhook_url=None, transfers=8, checkers=16, fast_list=True, source_kind="folder",
             keep_archive_after_extract=False):
    global _CONFIG_SAVE_HINT_SHOWN
    _CONFIG_SAVE_HINT_SHOWN = False  # 새 job마다 힌트를 다시 보여줄 수 있게 초기화

    source_kind = (source_kind or "folder").strip().lower()
    if source_kind not in ("folder", "folder_local", "file", "file_local", "folder_extract"):
        source_kind = "folder"

    if source_kind == "folder_extract":
        # 폴더 단위 일괄 다운로드+압축해제는 rclone 프로세스를 여러 번 실행하는
        # 완전히 다른 흐름이라, 아래 공유 로직(단일 subprocess + 진행률 파싱)을
        # 타지 않고 전용 함수로 위임한다.
        _run_folder_extract_job(
            job_id, rclone_path, config_path, rclone_remote, source_id, dest_folder_name,
            discord_webhook_url=discord_webhook_url,
            keep_archive_after_extract=keep_archive_after_extract,
        )
        return

    if source_kind == "file_local":
        # 개별 파일을 압축 해제 없이 "원본 그대로" 서버 로컬 절대경로에
        # 다운로드한다("file" 모드와 소스는 같지만 목적지가 rclone 원격이
        # 아니라 로컬이라는 점이 다름 - 압축 해제까지 하는 folder_extract와도
        # 다름: 이 모드는 폴더가 아니라 파일 하나, 압축을 풀지 않고 그대로
        # 저장). dest_folder_name은 start_copy_job()에서 이미 로컬 절대경로로
        # 검증/정규화되어 들어온다. copyid는 목적지 끝에 구분자가 있어야
        # 원본 파일명 그대로 그 디렉터리 아래에 저장하므로, 로컬 경로답게
        # OS에 맞는 구분자(os.sep)를 붙인다(rclone 원격 경로처럼 무조건 '/'를
        # 붙이면 Windows에서 구분자가 섞여버림).
        dest_path = dest_folder_name if dest_folder_name.endswith(os.sep) else dest_folder_name + os.sep
        cmd = [
            rclone_path,
            "backend",
            "copyid",
            f"{rclone_remote}:",
            source_id,
            dest_path,
            "--config",
            config_path,
            "--progress",
        ]
        source_line = f"[*] 소스 파일 ID      : {source_id}"
        mode_line = "[*] 복사 방식         : 개별 파일 로컬 다운로드 (rclone backend copyid, 압축 해제 없음)"
        final_dest_display = dest_path

    elif source_kind == "file":
        # 개별 파일(압축파일 1개)은 root_folder_id 트릭이 통하지 않는다 -
        # 그 트릭은 remote의 루트를 특정 "폴더"로 가장하는 방식이라 폴더
        # 전용이다. 대신 rclone의 ID 기반 단일 파일 복사 기능을 쓴다.
        #
        # !! 중요 !! `rclone copyid ...`는 실제 rclone에 존재하지 않는 명령이다
        # (v2.32.0에서 이렇게 구현했다가 "unknown command copyid for rclone"
        # 오류로 실패하는 것을 실사용 중 확인함). copyid는 독립 명령이 아니라
        # Google Drive 백엔드 전용 "backend 명령"이며, 반드시
        # `rclone backend copyid drive: ID path` 형태로 호출해야 한다
        # (rclone/rclone 커밋 e5190f14 "drive: implement 'rclone backend
        # copyid' command", rclone 공식 포럼 확인 완료). 내부적으로는
        # operations.Copy()를 그대로 쓰므로 --progress 통계 라인은 폴더
        # 모드와 동일하게 찍힌다.
        #
        # !! 주의 !! 이 모드의 목적지는 항상 "{rclone_remote}:경로" -
        # rclone 원격(=구글 드라이브) 안의 위치다. 로컬 디스크에 그대로
        # 받고 싶다면 이 모드가 아니라 "file_local"을 써야 한다 - 실사용
        # 중 이 모드에 로컬 경로(K:\...)를 입력했다가 rclone이 그걸 원격
        # 경로 문자열로 오인해서("libgdrive_oauth:K:다운로드/") 엉뚱하게
        # 동작한 사례가 있었다(로컬 저장이 되지 않고, 구글 드라이브 안에
        # "K:다운로드"라는 이름의 경로로 복사를 시도하게 됨).
        dest_path = f"{rclone_remote}:{dest_folder_name}"
        cmd = [
            rclone_path,
            "backend",
            "copyid",
            f"{rclone_remote}:",
            source_id,
            dest_path,
            "--config",
            config_path,
            "--progress",
        ]
        source_line = f"[*] 소스 파일 ID      : {source_id}"
        mode_line = "[*] 복사 방식         : 개별 파일 (rclone backend copyid)"
        final_dest_display = dest_path

    else:  # "folder" 또는 "folder_local" - root_folder_id 트릭은 둘 다 동일하고
           # 목적지만 rclone 원격이냐 로컬이냐로 갈린다.
        source_path = f"{rclone_remote},root_folder_id={source_id}:"
        dest_path = dest_folder_name if source_kind == "folder_local" else f"{rclone_remote}:{dest_folder_name}"

        # 기본값(rclone: --transfers=4, --checkers=8)만으로는 구글 드라이브
        # 서버사이드 복사(파일마다 독립적인 API 호출) 성능이 잘 안 나오는 경우가
        # 많다. 동시 처리 개수를 늘리면 API 라운드트립 지연을 훨씬 잘 가려준다
        # (단, 너무 높이면 구글 API 레이트리밋(403)에 걸려 오히려 재시도로
        # 느려질 수 있으니 설정에서 조절 가능하게 함). 로컬 목적지(folder_local)
        # 라도 다운로드 자체는 여전히 파일마다 개별 API 호출이라 동일하게 적용된다.
        cmd = [
            rclone_path,
            "copy",
            source_path,
            dest_path,
            "--config",
            config_path,
            "--progress",
            "--transfers",
            str(transfers),
            "--checkers",
            str(checkers),
        ]
        if fast_list:
            # 폴더/파일 개수가 많을 때 목록 조회 API 호출 수를 크게 줄여준다
            # (메모리를 좀 더 쓰는 대신 훨씬 빠르게 전체 목록을 가져옴).
            cmd.append("--fast-list")
        source_line = f"[*] 소스 폴더 ID      : {source_id}"
        concurrency_note = (
            f"--transfers={transfers} --checkers={checkers}" + (" --fast-list" if fast_list else "")
        )
        if source_kind == "folder_local":
            mode_line = f"[*] 복사 방식         : 폴더 전체 로컬 다운로드 (rclone copy, 압축 해제 없음) · {concurrency_note}"
        else:
            mode_line = f"[*] 동시성            : {concurrency_note}"
        final_dest_display = dest_path

    _append_log_line("=" * 60)
    _append_log_line(f"[*] Rclone 경로       : {rclone_path}")
    _append_log_line(f"[*] Config 파일 경로  : {config_path}")
    _append_log_line(source_line)
    _append_log_line(f"[*] 목적지 경로       : {final_dest_display}")
    _append_log_line(mode_line)
    _append_log_line("=" * 60)
    if source_kind in ("file_local", "folder_local"):
        _append_log_line("[*] 로컬로 다운로드를 시작합니다...\n")
    else:
        _append_log_line("[*] 서버사이드 복사를 시작합니다...\n")

    returncode = None
    process = None
    progress = {}  # 파일개수 줄과 바이트 줄이 서로 다른 순간에 나오므로 누적해서 합친다

    try:
        process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                **_SUBPROCESS_ISOLATION_KWARGS,
            )
        _update_state(pid=process.pid)

        for raw_line in process.stdout:
            try:
                decoded = raw_line.decode("utf-8", errors="replace")
            except Exception:
                decoded = raw_line.decode("latin-1", errors="ignore")

            # rclone --progress 는 캐리지리턴(\r)으로 같은 줄을 갱신하므로
            # 줄 단위 로그 뷰에서는 \r 기준으로 쪼개 마지막 조각만 남긴다.
            decoded = decoded.rstrip("\n")
            for piece in decoded.split("\r"):
                if piece:
                    _append_log_line(piece)
                    _maybe_explain_config_save_error(piece)
                    parsed = _parse_progress_line(piece)
                    if parsed:
                        progress.update(parsed)
                        # 두 "Transferred:" 줄(바이트 기준/파일개수 기준) 중
                        # 어느 쪽이 갱신되든 즉시 상태 파일에 반영한다. 서버사이드
                        # 복사에서는 파일개수 줄이 바이트 줄보다 더 자주 움직이는
                        # 경우가 있어서, 바이트 줄만 기다리면 "전체 진행률"이
                        # 안 움직이는 것처럼 보일 수 있었다.
                        _update_state(progress=dict(progress))

        process.wait()
        returncode = process.returncode
    except Exception as e:
        _append_log_line(f"\n[-] 스크립트 실행 중 예외 발생: {e}")

    state = _read_state() or {}
    cancelled = bool(state.get("cancel_requested"))

    if cancelled:
        status = "cancelled"
        _append_log_line("\n[-] 사용자 요청으로 중단되었습니다.")
        notify_text = f"⏹️ **[BookOasis] {_kind_label(source_kind)} 중단됨**\n목적지: `{final_dest_display}`"
    elif returncode == 0:
        status = "success"
        _append_log_line("\n[+] 서버사이드 복사가 성공적으로 완료되었습니다!")
        notify_text = f"✅ **[BookOasis] {_kind_label(source_kind)} 완료**\n목적지: `{final_dest_display}`"
        progress["percent"] = 100  # rclone의 마지막 갱신이 100%를 안 찍고 끝나는 경우 대비
        if progress.get("files_total"):
            progress["files_done"] = progress["files_total"]
            progress["files_percent"] = 100
    else:
        status = "error"
        _append_log_line(f"\n[-] 복사 중 오류가 발생했습니다. (종료 코드: {returncode})")
        notify_text = f"❌ **[BookOasis] {_kind_label(source_kind)} 실패** (종료 코드: {returncode})\n목적지: `{final_dest_display}`"

    _update_state(status=status, returncode=returncode, finished_at=time.time(), pid=None, progress=progress)
    _notify_discord(discord_webhook_url, notify_text)


def start_copy_job(rclone_path, config_path, rclone_remote, source_folder_url, dest_folder_name,
                    source_url_input=None, dest_input=None, discord_webhook_url=None,
                    transfers=8, checkers=16, fast_list=True, source_kind="folder",
                    keep_archive_after_extract=False):
    """
    유효성 검사 후 백그라운드 스레드로 rclone copy(또는 backend copyid, 또는
    다운로드+zip 압축 해제)를 시작합니다. 이미 실행 중인(그리고 실제로
    살아있는) job이 있으면 거부합니다.

    source_kind:
      - "folder"(기본): 폴더 전체를 rclone copy(root_folder_id 트릭)로 복사.
        dest_folder_name은 rclone 원격 경로("remote:path")의 path 부분.
      - "folder_local": "folder"와 소스(폴더 전체)는 같지만, 목적지가 rclone
        원격이 아니라 **서버의 로컬 절대경로**다 - 압축 해제 없이 폴더/파일
        구조를 그대로 그 경로 아래에 다운로드한다("folder" 모드에 로컬
        경로를 넣으면 rclone이 그걸 원격 경로 문자열로 오인해 엉뚱하게
        동작하는 사례가 있어 file/file_local과 같은 이유로 분리했다).
      - "file": 개별 압축파일 1개를 `rclone backend copyid`로 그대로 복사
        (구글 드라이브 -> 구글 드라이브). dest_folder_name도 rclone 원격 경로.
        목적지 경로 끝에 '/'를 보장해, rclone이 원본 파일명을 그대로 써서
        그 디렉터리 아래에 저장하도록 만든다.
      - "file_local": "file"과 소스(개별 파일 1개)는 같지만, 목적지가 rclone
        원격이 아니라 **서버의 로컬 절대경로**다(folder_extract와 같은 종류의
        경로) - 다만 압축 해제는 하지 않고 원본 파일을 그대로 그 경로 아래에
        저장한다("file" 모드에 로컬 경로를 넣으면 rclone이 그걸 원격 경로
        문자열로 오인해 엉뚱하게 동작하는 사례가 있어 분리했다).
      - "folder_extract": **소스 폴더**(파일 1개가 아니라 폴더) 안의 모든
        zip/cbz 파일을 재귀적으로 찾아, 파일마다 서버 로컬 스테이징 폴더로
        내려받은 뒤(`rclone backend copyid`) 파이썬 zipfile로 압축을 풀어
        dest_folder_name(**서버의 로컬 절대경로** - rclone 경로가 아님) 아래에
        원본 폴더 구조를 유지한 채 저장한다(예: 소스폴더/시즌1/01권.zip ->
        dest/시즌1/01권/). zip/cbz만 지원. 파일 하나가 실패해도 나머지는
        계속 처리하고 끝에 성공/실패 개수를 요약한다.
        keep_archive_after_extract가 True면 압축 해제 후 원본 압축파일도
        해당 폴더에 함께 남겨두고, False(기본)면 정리한다.

    source_url_input / dest_input: 변환 전, 사용자가 화면에 실제로 타이핑한 원본
    값(소스는 URL 그대로, 목적지는 마운트 경로일 수도 있는 원본). 새로고침 시
    입력창을 그대로 복원해주기 위해 job 상태에 함께 저장한다.

    discord_webhook_url: 설정된 경우, 복사가 끝났을 때(성공/실패/중단 모두)
    디스코드로 알림을 보낸다. 비어있으면 알림을 보내지 않는다.

    transfers / checkers / fast_list: rclone 동시성 옵션(폴더 모드에서만 사용).
    서버사이드 복사는 파일마다 독립적인 API 호출이라, 기본값(4/8)보다 늘리면
    훨씬 빨라지는 경우가 많다. 설정 화면에서 조절 가능.
    """
    rclone_path = (rclone_path or "").strip()
    config_path = (config_path or "").strip()
    rclone_remote = (rclone_remote or "").strip()
    dest_folder_name = (dest_folder_name or "").strip()

    source_kind = (source_kind or "folder").strip().lower()
    if source_kind not in ("folder", "folder_local", "file", "file_local", "folder_extract"):
        source_kind = "folder"

    try:
        transfers = max(1, int(transfers))
    except (TypeError, ValueError):
        transfers = 8
    try:
        checkers = max(1, int(checkers))
    except (TypeError, ValueError):
        checkers = 16

    if not rclone_path or not config_path or not rclone_remote:
        raise ConfigError("RCLONE_PATH / CONFIG_PATH / RCLONE_REMOTE가 설정되지 않았습니다. 설정 화면에서 먼저 저장해주세요.")
    if not dest_folder_name:
        raise ValueError("목적지 경로를 입력해주세요.")

    _validate_config(rclone_path, config_path)
    if source_kind == "folder_local":
        source_id = get_folder_id(source_folder_url)
        # "folder"와 소스(폴더 전체)는 같지만, 목적지는 rclone 원격이 아니라
        # file_local/folder_extract와 마찬가지로 "서버 로컬 절대경로"다 -
        # 압축은 전혀 건드리지 않고 원본 파일/폴더 구조를 그대로 받는다는
        # 점만 folder_extract와 다르다.
        if not os.path.isabs(dest_folder_name):
            raise ValueError(
                "폴더 다운로드 목적지는 서버의 로컬 절대경로여야 합니다 "
                "(예: POSIX는 /data/downloads, Windows는 K:\\다운로드)."
            )
        dest_folder_name_for_job = _normalize_local_abs_path(dest_folder_name)
        dest_path_display = dest_folder_name_for_job
    elif source_kind == "file_local":
        source_id = get_file_id(source_folder_url)
        # "file"과 소스(개별 파일)는 같지만, 목적지는 rclone 원격이 아니라
        # folder_extract와 마찬가지로 "서버 로컬 절대경로"다 - 압축은 풀지
        # 않고 원본 파일 그대로 받는다는 점만 folder_extract와 다르다.
        if not os.path.isabs(dest_folder_name):
            raise ValueError(
                "다운로드 목적지는 서버의 로컬 절대경로여야 합니다 "
                "(예: POSIX는 /data/downloads, Windows는 K:\\다운로드)."
            )
        dest_folder_name_for_job = _normalize_local_abs_path(dest_folder_name)
        dest_path_display = dest_folder_name_for_job
    elif source_kind == "file":
        source_id = get_file_id(source_folder_url)
        # copyid는 목적지 경로 끝의 '/' 유무로 "디렉터리 안에 원본 파일명대로
        # 저장" 여부를 판단하므로, 항상 슬래시를 보장해 원본 파일명을 유지한다.
        dest_folder_name_for_job = dest_folder_name.rstrip("/") + "/"
        dest_path_display = f"{rclone_remote}:{dest_folder_name_for_job}"
    elif source_kind == "folder_extract":
        source_id = get_folder_id(source_folder_url)
        # 이 모드는 rclone 원격 경로가 아니라 "서버 로컬 절대경로"를 받는다 -
        # 압축을 풀어놓을 실제 디스크 위치이기 때문. 상대경로/마운트 경로가
        # 섞여 들어오면 엉뚱한 곳에 풀릴 수 있으므로 절대경로만 허용한다.
        # os.path.isabs()는 실행 중인 OS 기준으로 판단하므로, POSIX 서버에서는
        # '/data/...'가, Windows 서버에서는 'K:\\다운로드'나 'K:/다운로드'가
        # 각각 절대경로로 정상 인식된다(예전엔 '/'로 시작하는지만 검사해서
        # Windows 드라이브 경로가 전부 거부됐었음 - v2.35.0에서 수정).
        if not os.path.isabs(dest_folder_name):
            raise ValueError(
                "압축 해제 목적지는 서버의 로컬 절대경로여야 합니다 "
                "(예: POSIX는 /data/comics/시리즈명, Windows는 K:\\다운로드\\시리즈명)."
            )
        dest_folder_name_for_job = _normalize_local_abs_path(dest_folder_name)
        dest_path_display = dest_folder_name_for_job
    else:
        source_id = get_folder_id(source_folder_url)
        dest_folder_name_for_job = dest_folder_name
        dest_path_display = f"{rclone_remote}:{dest_folder_name_for_job}"

    existing = _read_state()
    if existing and existing.get("status") == "running" and _process_is_alive(existing.get("pid")):
        raise RuntimeError("이미 실행 중인 복사 작업이 있습니다. 완료 또는 중단 후 다시 시도해주세요.")

    job_id = uuid.uuid4().hex[:12]
    _reset_log()
    _write_state({
        "job_id": job_id,
        "status": "running",
        "pid": None,
        "cancel_requested": False,
        "returncode": None,
        "started_at": time.time(),
        "finished_at": None,
        "source_id": source_id,
        "source_kind": source_kind,
        "dest_path": dest_path_display,
        # 새로고침 시 입력창 복원용 원본 값
        "source_url_input": (source_url_input or source_folder_url or "").strip(),
        "dest_input": (dest_input or dest_folder_name or "").strip(),
        "progress": {},
    })

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, rclone_path, config_path, rclone_remote, source_id, dest_folder_name_for_job,
              discord_webhook_url, transfers, checkers, fast_list, source_kind, keep_archive_after_extract),
        daemon=True,
    )
    thread.start()
    return job_id


def cancel_current_job():
    """실행 중인 job을 중단합니다. PID에 SIGTERM을 보내고, 응답이 없으면
    잠시 후 SIGKILL로 강제 종료합니다."""
    state = _read_state()
    if not state or state.get("status") != "running":
        return False, "진행 중인 복사 작업이 없습니다."

    pid = state.get("pid")
    _update_state(cancel_requested=True)

    if not pid:
        # 아직 rclone 프로세스가 실제로 뜨기 전(아주 짧은 순간)일 수 있음 -
        # cancel_requested만 세워두면 프로세스가 뜬 직후 상태를 봐서
        # 알아서 정리되도록 하는 편이 안전하지만, 여기서는 바로 응답한다.
        return True, "중단을 요청했습니다."

    if not _process_is_alive(pid):
        # 이미 끝난 프로세스 - _run_job이 곧 상태를 정리할 것
        return True, "이미 종료된 작업입니다."

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        # 이미 종료된 프로세스이거나(Windows에서는 OpenProcess 실패가
        # ProcessLookupError가 아니라 일반 OSError로 올 수 있음) 그 사이
        # 이미 사라진 경우 - 무해하므로 무시한다.
        pass
    except Exception as e:
        return False, f"중단 요청 중 오류: {e}"

    def _force_kill_if_still_alive():
        time.sleep(5)
        if _process_is_alive(pid):
            try:
                os.kill(pid, _HARD_KILL_SIGNAL)
            except Exception:
                pass

    threading.Thread(target=_force_kill_if_still_alive, daemon=True).start()
    return True, "중단을 요청했습니다. 잠시 후 종료됩니다."


def force_reset_job():
    """job_state.json/job.log를 강제로 초기화한다 (job이 없는 상태로 되돌림).

    "이미 실행 중인 작업이 있습니다"가 실제로는 끝났는데도 계속 뜨는 등,
    self-heal 로직으로도 안 풀리는 꼬인 상태를 사용자가 직접 빠져나올 수
    있게 하는 최후의 수단. rclone 프로세스가 실제로 살아있다면(비정상적인
    상황이지만) 먼저 정리 시도한 뒤 상태를 초기화한다.

    삭제가 실패해도(예: 권한 문제) 예외를 조용히 삼키지 않는다 - 예전엔
    실패해도 "성공했다"고 잘못 알려줘서, 진짜 원인(파일 삭제 권한 등)이
    안 보이는 문제가 있었다. 삭제 후 실제로 파일이 없어졌는지 다시
    확인해서, 남아있으면 왜 실패한 것으로 보이는지와 함께 알려준다.
    """
    state = _read_state()
    if state:
        pid = state.get("pid")
        if pid and _process_is_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    errors = []
    with _STATE_LOCK:
        for path in (STATE_FILE, LOG_FILE):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{path}: {e}")

    # 삭제 시도 후 실제로 사라졌는지 재확인 (조용한 실패 방지)
    still_there = [p for p in (STATE_FILE, LOG_FILE) if os.path.exists(p)]
    if still_there:
        abs_paths = ", ".join(os.path.abspath(p) for p in still_there)
        detail = "; ".join(errors) if errors else "삭제 명령은 예외 없이 실행됐지만 파일이 그대로 남아있습니다."
        return False, (
            f"초기화에 실패했습니다 (파일 삭제 권한 문제일 수 있습니다). "
            f"남은 파일: {abs_paths} · 상세: {detail}"
        )

    return True, "작업 상태를 초기화했습니다. 다시 시작할 수 있습니다."


def get_last_job_status():
    """get_dashboard_data()가 폴링용으로 쓰는, 가장 최근 job의 상태 + 로그."""
    state = _read_state()
    if state is None:
        return None

    # status가 "running"인데 실제 프로세스가 죽어있으면(예: 컨테이너 재시작으로
    # 스레드 자체가 사라진 경우) 좀비 상태로 영원히 "진행 중"으로 보이는 것을
    # 막기 위해 여기서 정리한다. 단, job을 막 시작해서 아직 pid가 기록되기
    # 전(Popen 호출 직전)일 수 있으므로 시작 직후 몇 초간은 봐준다.
    just_started = (time.time() - (state.get("started_at") or 0)) < 5
    if state.get("status") == "running" and not state.get("pid") and just_started:
        pass  # 아직 pid 기록 전 - 정상, 다음 폴링 때 다시 확인
    elif state.get("status") == "running" and not _process_is_alive(state.get("pid")):
        state = _update_state(
            status="error",
            returncode=None,
            finished_at=time.time(),
        )
        _append_log_line("\n[-] 서버가 재시작되어 진행 상황을 더 이상 추적할 수 없습니다. (복사가 이미 끝났을 수도 있습니다 - rclone remote에서 직접 확인해주세요)")

    result = dict(state)
    result["lines"] = _read_log_lines()
    return result


def read_raw_state():
    """job_state.json을 가공 없이 그대로 읽는다.

    get_last_job_status()와 달리 좀비 체크나 로그 파일 읽기 같은 부가 처리를
    하지 않는, 가벼운 조회용."""
    return _read_state()


def get_data_dir_abs():
    """DATA_DIR(./plugins/data/rclone_g2g_copy, cwd 기준 상대경로)의 실제
    절대경로. 화면 배너/로그에 노출해서, "강제 초기화해도 그대로임" 같은
    문제가 생겼을 때 앱이 실제로 어느 경로를 쓰고 있는지 바로 확인할 수
    있게 한다 (여러 워커/프로세스가 서로 다른 작업 디렉터리에서 떠서 각자
    다른 파일을 보고 있는 경우 등을 의심해볼 수 있음)."""
    return os.path.abspath(DATA_DIR)
