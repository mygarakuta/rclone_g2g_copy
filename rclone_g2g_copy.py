# -*- coding: utf-8 -*-
"""
rclone_g2g_copy (폴더 복사 - rclone G2G)
--------------
원본 스크립트 g2g.py(파일 상단 상수를 직접 고쳐서 실행하던 rclone 서버사이드
복사 스크립트)를 카테고리탭 지원 BookOasis 플러그인으로 이식한 것입니다.

- scan_scheduler.py에서 실제로 확인된 계약을 그대로 따릅니다: 커스텀 Flask
  Blueprint/라우트를 따로 두지 않고, BaseMetadataProvider 표준 계약
  (search/apply/get_dashboard_data)만으로 동작합니다.
- 설정(RCLONE_PATH/CONFIG_PATH/RCLONE_REMOTE)은 config_schema + settings.html로
  선언하고, 베이스 헬퍼 self.get_plugin_config(db_type, default=...)로 읽습니다
  (guide_plugins.md "플러그인 DB 게이트웨이(권장)" 절에 명시된 정식 시그니처 —
  이전 버전은 self.get_db_gateway(db_type).get_plugin_config(self.id)를 잘못
  호출하고 있어서 항상 빈 dict로 조용히 폴백되고 있었음. 수정 완료).
- 실행(복사 시작)은 좌측 사이드바 category_tab 풀페이지(index.html/script.js)에서
  POST /api/media/books/0/apply-metadata (book_id=0 더미, plugin_board에서 확인된
  범용 액션 채널)를 호출해 apply(db_type, book_id, item_data)로 들어옵니다.
  item_data = {"action": "start_copy", "source_url": ..., "dest_folder_name": ...}
- 진행 상황(rclone --progress 로그)은 GET /api/media/dashboard/widgets/
  rclone_g2g_copy/data 로 들어오는 get_dashboard_data(db_type, limit)를
  프론트가 주기적으로 폴링해서 가져갑니다. (풀페이지 뷰이므로 db_type/limit은
  사실상 무시하고, 가장 최근 시작한 job 하나의 상태/로그를 그대로 반환)

!! 이 플러그인은 subprocess로 rclone 실행 파일을 직접 실행합니다 !!
guide_plugins.md 2장 "서브프로세스 실행 차단(기본값)" 규칙에 따라, 서버 관리자가
.env에 ALLOW_PLUGIN_SUBPROCESS=true를 설정하지 않으면 이 플러그인은 로드 자체가
거부됩니다. (→ 이 배포 환경에서는 이미 설정 완료됨)

변경 이력(이번 수정, v2.39.1):
- "소스 종류" 라디오 라벨을 "폴더"/"개별 파일"에서 **"구글 드라이브 폴더"/
  "구글 드라이브 개별 파일"**로 바꿨습니다. 소스는 항상 구글 드라이브이고
  "목적지 종류"(원격/로컬)와는 별개라는 점을 라디오 이름만 보고도 바로
  알 수 있도록 명시했습니다(index.html만 수정, 기능 변경 없음).

변경 이력(v2.39.0 — 화면 구조 전면 개편):
- **"소스 종류" 라디오 하나에 5가지 모드를 욱여넣던 구조를 버리고, "소스
  종류"(폴더/개별 파일, 2개)와 "목적지 종류"(원격/로컬-그대로/로컬-압축해제,
  3개)를 완전히 독립된 두 개의 라디오 그룹으로 분리했습니다.** 스크린샷으로
  "이 둘은 원래 서로 다른 축 아니냐, 이렇게 나누는 게 맞지 않냐"는 지적을
  받고 동의해서 반영했습니다. 기존에는 조합 하나하나를 전부 별도 라디오로
  나열해서(폴더 전체/폴더 전체 로컬/개별 파일/개별 파일 로컬/일괄 압축해제)
  선택지가 5개로 늘어났고, 두 축이 뒤섞여 화면도 복잡했습니다(신고해주신
  스크린샷의 겹침 현상도 그 여파로 보입니다). 2×3 매트릭스로 분리하니
  선택지는 여전히 5개 라디오(2+3)지만 훨씬 명확해졌고, **이전에는 만들 수
  없었던 여섯 번째 조합 "개별 파일 → 로컬 압축 해제"(`file_extract`)도
  자연스럽게 생겼습니다** - 폴더 스캔 없이 파일 하나만 다운로드+압축 해제할
  때 씁니다(`_run_file_extract_job()`).
  - 서버로 보내는 `source_kind` 값 자체(`folder`/`folder_local`/`file`/
    `file_local`/`folder_extract`/`file_extract`)는 그대로라 기존
    `job_state.json`이나 외부 연동과 호환됩니다 - 화면(script.js)이 두
    라디오 그룹의 선택을 이 여섯 값 중 하나로 조합/분해(`COMBINED_KIND_MAP`
    / `KIND_TO_SHAPE_AND_DEST`)할 뿐입니다.
  - Windows 로컬 경로 자동 전환(v2.38.0)도 그대로 동작하며, 이제는 "목적지
    종류" 라디오만 바꾸면 되므로 로직이 더 단순해졌습니다(소스 종류는
    건드리지 않음).
  - jsdom으로 실제 DOM에 script.js를 실행시켜, 두 라디오 그룹이 서로
    독립적으로 동작하는지(한쪽을 바꿔도 다른 쪽이 유지되는지), 여섯 번째
    조합(file_extract)에 실제로 도달 가능한지, Windows 자동 전환이 목적지
    종류만 바꾸고 소스 종류는 안 건드리는지까지 전부 통합 테스트로 확인했습니다.

변경 이력(v2.38.0):
- **목적지 경로가 누가 봐도 Windows 로컬 경로(`K:\다운로드`, `\\서버\공유` 등)면,
  "폴더 전체"/"개별 압축파일"(원격) 모드를 선택한 채로 두어도 자동으로
  "폴더 전체 로컬로 다운로드"/"개별 파일 로컬로 다운로드" 모드로 전환되도록
  했습니다.** "5개 모드를 매번 직접 골라야 하냐, Windows인지 자동으로
  판별할 수 있는 것 아니냐"는 질문에 대한 답입니다 - 결론은 "부분적으로
  가능"입니다: Windows 드라이브 문자/UNC 경로는 rclone 원격 상대경로
  관례에 절대 나오지 않는 형태라 100% 확신할 수 있어 자동 전환이
  안전하지만, POSIX 절대경로(`/data/...`)는 rclone 원격 상대경로 관례도
  똑같이 `/`로 시작해서 문자열만으로는 "로컬 디스크"인지 "원격 안의 그
  경로"인지 구분이 안 되므로 그 경우는 자동 전환하지 않고 사용자가 고른
  모드를 그대로 존중합니다(잘못 추측해서 반대로 처리하면 더 헷갈리는
  사고가 나기 때문). `logic.looks_like_windows_local_path()`에 판별
  로직을 두고, 서버(`_start_copy()`)와 화면(`script.js`) 양쪽에서 동일한
  규칙을 적용합니다 - 화면에서 입력하는 즉시 라디오가 바뀌고, 혹시
  그 전환 없이 요청이 오더라도(예: 구버전 캐시, 외부 연동) 서버가 한 번
  더 같은 판정을 해서 잘못된 조합으로 실행되는 것을 막습니다.

변경 이력(v2.37.0):
- **"폴더 전체를 압축 해제 없이 서버 로컬로 그대로 다운로드"하는
  "folder_local" 모드를 추가했습니다.** 사용자가 세 가지 시나리오로 요구
  사항을 정리해 확인을 요청했습니다: ① 폴더 → 목적지 폴더 하부에 폴더
  그대로 복사, ② 개별 파일 → 목적지 폴더 하부에 파일 그대로 복사, ③ 압축
  파일 → 임시로 받은 뒤 목적지 폴더 하부에 압축 해제(폴더 구조 포함). ②는
  기존 `file_local`, ③은 기존 `folder_extract`가 이미 정확히 대응하고
  있었지만, ①(폴더를 압축 해제 없이 그대로 로컬에 복사)에 대응하는 모드가
  없어서 새로 추가했습니다. 소스는 "folder"(폴더 전체)와 동일하지만,
  목적지가 rclone 원격이 아니라 file_local/folder_extract와 같은 서버 로컬
  절대경로입니다. `rclone copy`(root_folder_id 트릭)를 그대로 쓰되 목적지만
  로컬 경로로 바뀝니다 - `--transfers`/`--checkers`/`--fast-list` 동시성
  옵션도 "folder" 모드와 동일하게 적용됩니다(여러 파일을 받으므로 의미가
  있음, file_local과의 차이점). 소스 종류 라디오에 "📁→💾 폴더 전체
  로컬로 다운로드(압축 해제 없음)"가 추가됐습니다.

변경 이력(v2.36.0):
- **개별 파일을 압축 해제 없이 서버 로컬로 그대로 다운로드하는 "file_local"
  모드를 추가했습니다.** 실사용 중 "개별 압축파일" 모드(`file`)의 목적지에
  로컬 경로(`K:\다운로드`)를 입력했다가, rclone이 그걸 원격 경로 문자열로
  오인해 `libgdrive_oauth:K:다운로드/`처럼 엉뚱하게 동작(로컬 저장이 되지
  않음)하는 사례가 보고됐습니다. 원인: `file` 모드는 "구글 드라이브 →
  구글 드라이브" 전용으로 설계되어 있어 목적지가 항상 `{rclone_remote}:`
  접두사가 붙는 rclone 원격 경로로 취급됩니다. 압축 해제 없이 파일 하나를
  서버 로컬 디스크에 그대로 받는 용도의 모드가 없었던 것이 근본 원인이라,
  새 모드를 추가해 그 빈틈을 메꿨습니다. 소스는 "file"과 동일(개별 파일
  URL/ID)하지만, 목적지는 folder_extract와 같은 종류의 **서버 로컬
  절대경로**이고 압축은 풀지 않습니다. 소스 종류 라디오에 "📦→💾 개별 파일
  로컬로 다운로드(압축 해제 없음)"가 추가됐습니다.

변경 이력(v2.35.1):
- **"폴더 안 압축파일 일괄 압축 해제" 모드의 목적지 필드 라벨에 Windows
  예시(`K:\다운로드\시리즈명`)를 플레이스홀더뿐 아니라 라벨 텍스트 자체에도
  항상 보이도록 추가했습니다** (플레이스홀더는 입력을 시작하면 사라져서
  놓치기 쉬웠음).
- 배치 다운로드의 스테이징 경로(파일마다 임시로 받는 로컬 폴더) 끝에 구분자를
  붙이는 로직이 항상 `/`를 붙이고 있어, Windows에서는 역슬래시와 슬래시가
  섞인 경로(예: `...\\staging\\job\\1/`)가 rclone에 전달되고 있었습니다. `os.sep`
  기준으로 OS에 맞는 구분자를 쓰도록 고쳤습니다(이 경로는 항상 서버
  로컬 경로이므로 rclone 원격 경로와 달리 OS 구분자를 따라야 함).

변경 이력(v2.35.0 — Windows 크래시 핫픽스):
- **rclone_g2g_copy가 job을 실행하는 동안 BookOasis 전체가 몇 초 만에 강제
  종료되는 심각한 버그를 수정했습니다 (Windows 배포에서만 발생).** 실사용
  중이신 분이 "K 드라이브로 로컬 저장을 시도했더니 실패하면서 BookOasis가
  꺼지는 것 같다"고 보고해주셔서 발견했습니다. 근본 원인은 `logic.py`의
  `_process_is_alive()`가 프로세스 생존 확인에 썼던 `os.kill(pid, 0)` -
  Windows API에서는 시그널 값 0이 `CTRL_C_EVENT`와 동일해서, 이 호출이
  실제로는 그 콘솔에 연결된 모든 프로세스에 Ctrl+C를 전파해버립니다. 이
  함수는 job이 "실행 중"인 동안 프론트엔드가 몇 초마다 폴링할 때마다
  호출되므로, 어떤 소스 종류(폴더/파일/폴더 일괄 압축해제)로 시작하든
  Windows에서는 시작 직후 재현됐습니다. `_process_is_alive()`를 Windows
  전용 분기(ctypes OpenProcess/GetExitCodeProcess)로 바꾸고, 모든 rclone
  하위 프로세스를 부모 콘솔/프로세스 그룹과 분리하도록(creationflags/
  start_new_session) 방어적으로 고쳤습니다. `signal.SIGKILL`(Windows에
  없는 속성) 참조도 안전한 대체값으로 바꿨습니다. 자세한 것은 logic.py
  상단 주석과 `_process_is_alive()` 참고.
- **"폴더 안 압축파일 일괄 압축 해제" 모드의 목적지 절대경로 검증이
  Windows 경로(`K:\다운로드` 등)를 전부 거부하던 버그도 함께 수정했습니다.**
  `dest_folder_name.startswith("/")`(POSIX 전용)를 `os.path.isabs(...)`로
  바꿔, 실행 중인 OS에 맞게 올바르게 절대경로를 판정합니다.

변경 이력(v2.34.0):
- **"다운로드 후 압축 해제" 모드의 소스를 "개별 파일 1개"에서 "폴더 전체(일괄
  처리)"로 바꿨습니다.** source_kind 값도 `file_extract` → `folder_extract`로
  변경했습니다(폴더 모드와 마찬가지로 소스가 "폴더"라는 점을 이름에 반영).
  이제 소스로 구글 드라이브 **폴더** 링크/ID를 입력하면:
  1. `rclone lsjson --recursive`로 그 폴더(하위 폴더 포함) 안의 zip/cbz 파일을
     전부 찾고,
  2. 파일마다 순서대로 `rclone backend copyid`로 스테이징 폴더에 내려받은 뒤
     파이썬 zipfile로 압축을 풀어, 목적지 로컬 절대경로 아래에 **원본 폴더
     구조를 그대로 유지**해서 배치합니다 (예: 소스폴더/시즌1/01권.zip →
     목적지/시즌1/01권/).
  파일 하나가 실패해도 나머지는 계속 처리하고, 끝에 성공/실패 개수를
  요약해서 로그와 디스코드 알림에 보여줍니다. 진행률 바는 "전체 파일 수 대비
  처리한 개수"를 기준으로 표시됩니다. 자세한 것은 logic.py의
  `_run_folder_extract_job()`/`_list_archive_files_in_folder()` 참고.

변경 이력(v2.33.0):
- **다운로드 후 압축 해제("file_extract") 모드를 처음 추가했습니다** (v2.34.0에서
  소스를 폴더 단위 일괄 처리로 재설계함 - 위 항목 참고). rclone은 전송(복사)
  전용 도구라 압축 해제 기능이 없으므로, ① rclone backend copyid로 압축파일을
  서버 로컬 스테이징 폴더에 내려받고 ② 파이썬 표준 라이브러리 zipfile로 최종
  목적지(서버 로컬 절대경로)에 압축을 푸는 2단계 구조를 도입했습니다(zip/cbz만
  지원, zip slip 방지 검증 포함). 이 모드에서는 "목적지 경로"가 rclone 원격
  경로가 아니라 서버의 로컬 절대경로를 의미합니다(마운트 접두사 변환
  미적용). 설정에 KEEP_ARCHIVE_AFTER_EXTRACT(선택, 기본 꺼짐)를 추가해 압축
  해제 후 원본 압축파일을 목적지 폴더에 함께 남겨둘지 고를 수 있습니다.

변경 이력(v2.32.1 — 핫픽스):
- **v2.32.0에서 추가한 개별 파일 복사가 실제로는 동작하지 않는 버그를
  수정했습니다.** `rclone copyid ...`로 호출했는데, 실사용 환경에서
  `Error: unknown command "copyid" for "rclone"`로 실패하는 것을 확인함 -
  `copyid`는 독립 명령이 아니라 Google Drive 백엔드 전용 "backend 명령"이라,
  반드시 `rclone backend copyid drive: ID path` 형태로 호출해야 했습니다
  (rclone/rclone 커밋 e5190f14 "drive: implement 'rclone backend copyid'
  command" 및 rclone 공식 포럼 확인). cmd를
  `[rclone_path, "backend", "copyid", f"{remote}:", id, dest, ...]`로
  수정했습니다. `backend copyid`도 내부적으로 표준 `operations.Copy()`를
  그대로 쓰므로, `--progress` 진행률 파싱 로직은 수정 없이 그대로 재사용됩니다.

변경 이력(v2.32.0):
- 갱신된 guide_plugins.md 반영: subprocess 실행 플러그인 권장 사항에 따라
  admin_only=True를 추가했습니다 (일반 계정에게는 사이드바 탭/데이터 자체가
  완전히 숨겨집니다 - 실행 자체는 apply-metadata 라우트가 이미 admin 전용이라
  기존에도 관리자만 가능했지만, 탭 노출 자체는 이제 fail-closed로 막힙니다).
- **폴더 단위뿐 아니라 개별 압축파일(zip/cbz 등) 1개 단위 복사를 지원**하도록
  변경했습니다. index.html에 "소스 종류(폴더/개별 파일)" 라디오 버튼을
  추가했고, item_data에 source_kind("folder" 기본값 | "file")를 실어 보내면
  logic.py가 그에 맞춰 다른 rclone 명령을 사용합니다:
    - 폴더: 기존과 동일하게 root_folder_id 트릭 + `rclone copy`
    - 개별 파일: 그 트릭이 통하지 않으므로(폴더 전용 트릭) rclone의 ID 기반
      단일 파일 복사 명령 `rclone backend copyid drive: <파일ID> <목적지경로>/`를
      사용합니다(목적지 경로 끝에 '/'를 보장해 원본 파일명을 그대로 유지).
  자세한 것은 logic.py의 get_file_id() / _run_job() 주석 참고.

변경 이력(v2.31.0):
- GAS(Google Apps Script) 백엔드를 완전히 제거했습니다. gas_logic.py import,
  GAS_WEBAPP_URL/GAS_SHARED_SECRET 설정 필드, method="gas" 분기, 백엔드 선택
  체크박스 연동(get_dashboard_data의 gas_configured 필드)을 모두 삭제했습니다.
  rclone.conf/Docker 볼륨 마운트 이슈(README 참고)는 그대로 남아있으니, 필요하면
  README의 "device or resource busy" 안내를 참고하세요.
- _get_config()가 존재 여부가 불확실했던 게이트웨이 경유 호출 대신
  self.get_plugin_config(db_type, default=...)를 쓰도록 수정했습니다.
- update_manifest.raw_base_url을 실제 저장소(mygarakuta/rclone_g2g_copy)로
  수정하고, files 목록에서 gas_logic.py/gas/Code.gs를 제거했습니다.

!! 여전히 확인 필요 (검증 안 됨) !!
- apply-metadata 응답 JSON 형태(성공/실패 필드명)는 정확히 확인되지 않아
  script.js에서 `success`/`message`로 가정했습니다 - 실제 응답이 다르면
  script.js의 파싱 부분만 고치면 됩니다.
- category_tab.icon 값("fa-solid fa-clone")은 실제 아이콘 셋 확인 전 가정입니다.
"""
from plugins.metadata.base import BaseMetadataProvider
import json

from .logic import (
    ConfigError,
    start_copy_job,
    cancel_current_job,
    force_reset_job,
    get_last_job_status,
    read_raw_state,
    get_data_dir_abs,
    to_rclone_relative_path,
    resolve_mount_prefix,
    list_rclone_remotes,
    looks_like_windows_local_path,
)


class RcloneG2gCopyProvider(BaseMetadataProvider):
    id = "rclone_g2g_copy"
    name = "폴더 복사 (rclone G2G)"
    is_searchable = False

    # 갱신된 guide_plugins.md 2장: subprocess로 외부 실행 파일을 직접 실행하는
    # 플러그인은 admin_only=True로 관리자 외 전원에게 화면/데이터 자체를 숨기는
    # 것이 권장된다. 이 플러그인은 rclone 실행 파일을 직접 구동하므로 적용한다.
    # (apply-metadata 라우트 자체가 이미 @admin_required라 실행 자체는 예전에도
    # 관리자만 가능했지만, admin_only가 없으면 일반 계정에게 사이드바 탭 자체는
    # 권한 매트릭스 설정에 따라 보일 수 있었다 - admin_only는 그 노출 자체를
    # fail-closed로 막아준다.)
    admin_only = True

    # 설정 화면(settings.html)과 1:1로 대응되는 필드 목록.
    # (random_gallery/pixiv_ranking 작업에서 확인된 config_schema 형식)
    config_schema = [
        {
            "key": "RCLONE_PATH",
            "label": "RCLONE_PATH",
            "type": "text",
            "default": "/usr/bin/rclone",
        },
        {
            "key": "CONFIG_PATH",
            "label": "CONFIG_PATH (rclone.conf 절대경로)",
            "type": "text",
            "default": "",
        },
        {
            "key": "RCLONE_REMOTE",
            "label": "RCLONE_REMOTE (rclone.conf에 등록된 remote 이름)",
            "type": "text",
            "default": "",
        },
        {
            "key": "MOUNT_PREFIX",
            "label": "호스트/도커 마운트 경로 접두사 (선택 — 비워두면 /mnt/<RCLONE_REMOTE> 자동 사용)",
            "type": "text",
            "default": "",
        },
        {
            "key": "DISCORD_WEBHOOK_URL",
            "label": "디스코드 웹훅 URL (선택 — 비워두면 알림 없음)",
            "type": "password",
            "default": "",
        },
        {
            "key": "RCLONE_TRANSFERS",
            "label": "동시 전송 개수 (--transfers, 기본 8)",
            "type": "text",
            "default": "8",
        },
        {
            "key": "RCLONE_CHECKERS",
            "label": "동시 목록조회 개수 (--checkers, 기본 16)",
            "type": "text",
            "default": "16",
        },
        {
            "key": "RCLONE_FAST_LIST",
            "label": "빠른 목록조회 (--fast-list)",
            "type": "select",
            "default": "true",
            "options": [
                {"value": "true", "label": "켜짐 (권장 — 파일/폴더가 많을 때 훨씬 빠름)"},
                {"value": "false", "label": "꺼짐 (메모리가 매우 부족한 환경에서만)"},
            ],
        },
        {
            "key": "KEEP_ARCHIVE_AFTER_EXTRACT",
            "label": "압축 해제 후 원본 압축파일도 목적지 폴더에 함께 보관 ('다운로드 후 압축 해제' 모드 전용)",
            "type": "checkbox",
            "default": False,
        },
    ]

    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        "raw_base_url": "https://raw.githubusercontent.com/mygarakuta/rclone_g2g_copy/refs/heads/main/",
        "files": [
            "rclone_g2g_copy.py",
            "logic.py",
            "__init__.py",
            "VERSION",
            "index.html",
            "style.css",
            "script.js",
            "settings.html",
            "settings.css",
            "settings.js",
            "requirements.txt",
        ],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    # 좌측 사이드바 독립 카테고리 메뉴 등록 (scan_scheduler와 동일한 계약)
    category_tab = {
        "title": "폴더 복사 (rclone G2G)",
        "icon": "fa-solid fa-clone",  # TODO: 실제 아이콘 셋 확인 필요
        "order": 96,
        "sessions": "all",
    }

    # ------------------------------------------------------------------
    # 설정 조회 헬퍼
    # ------------------------------------------------------------------
    def _get_config(self, db_type):
        """guide_plugins.md "플러그인 DB 게이트웨이(권장)" 절의 정식 헬퍼를 사용한다.

        이전 버전은 self.get_db_gateway(db_type).get_plugin_config(self.id)를
        호출했는데, 이는 게이트웨이 객체에 없는 메서드일 가능성이 높아 예외가
        try/except로 조용히 삼켜지고 항상 빈 dict로 폴백되고 있었다 (= 설정
        화면에서 저장한 값이 절대 반영되지 않는 상태). self.get_plugin_config는
        BaseMetadataProvider 자체의 헬퍼이며, default 인자로 config_schema
        기본값을 그대로 넘기면 누락된 키도 항상 채워진 상태로 돌려준다.
        """
        defaults = {item["key"]: item.get("default", "") for item in self.config_schema}
        return self.get_plugin_config(db_type, default=defaults)

    # ------------------------------------------------------------------
    # 필수 계약: 이 플러그인은 도서 메타데이터 검색과 무관한 유틸리티
    # ------------------------------------------------------------------
    def search(self, db_type, query):
        return []

    def apply(self, db_type, book_id, item_data):
        """book_id=0으로 호출되는 범용 액션 채널 (plugin_board/scan_scheduler와 동일 패턴).

        item_data = {"action": "start_copy", "source_url": ..., "dest_folder_name": ...}
        또는 item_data = {"action": "cancel_copy"}
        """
        try:
            return self._dispatch_apply(db_type, item_data)
        except Exception as exc:  # noqa: BLE001
            return False, "예상치 못한 오류가 발생했습니다: %s" % exc

    def _dispatch_apply(self, db_type, item_data):
        if not isinstance(item_data, dict):
            return False, "유효하지 않은 요청 데이터 형식입니다."

        action = str(item_data.get("action", "")).strip()

        if action == "start_copy":
            return self._start_copy(db_type, item_data)
        if action == "cancel_copy":
            return self._cancel_copy(db_type)
        if action == "reset_job":
            return force_reset_job()
        if action == "list_remotes":
            return self._list_remotes(item_data)

        return False, "지원하지 않는 action입니다: %s" % action

    def _cancel_copy(self, db_type):
        """진행 중인 job이 있으면 PID에 시그널을 보내 중단한다."""
        state = read_raw_state()
        if not state:
            return False, "진행 중인 복사 작업이 없습니다."
        return cancel_current_job()

    def _list_remotes(self, item_data):
        """설정 화면(settings.js)이 RCLONE_REMOTE 풀다운을 채울 때 호출.

        저장된 값이 아니라, 사용자가 지금 입력창에 타이핑 중인 CONFIG_PATH를
        그대로 넘겨받아 미리보기를 제공한다 (저장을 먼저 안 해도 되도록).
        apply()는 (bool, message) 문자열만 돌려줄 수 있어서, 목록은
        message 안에 JSON으로 실어 보낸다 - script.js에서 JSON.parse해서 씀.
        """
        config_path = str(item_data.get("config_path", "")).strip()
        remotes = list_rclone_remotes(config_path)
        return True, json.dumps({"remotes": remotes})

    def _start_copy(self, db_type, item_data):
        source_url = str(item_data.get("source_url", "")).strip()
        dest_input = str(item_data.get("dest_folder_name", "")).strip()
        # "folder"(소스 폴더 전체를 원격에 그대로 복사) / "folder_local"(소스
        # 폴더 전체를 압축 해제 없이 서버 로컬에 그대로 다운로드) /
        # "file"(개별 압축파일 1개 그대로 원격에 복사) / "file_local"(개별
        # 파일 1개를 압축 해제 없이 서버 로컬에 그대로 다운로드) /
        # "folder_extract"(소스 폴더 안의 압축파일들을 각각 다운로드 후
        # 로컬에 압축 해제) / "file_extract"(개별 파일 1개를 다운로드 후
        # 로컬에 압축 해제 - folder_extract와 달리 폴더 스캔 없이 파일
        # 하나만 처리).
        # 화면(index.html)에서는 이 6가지를 "소스 종류"(폴더/파일)와
        # "목적지 종류"(원격/로컬/로컬+압축해제) 두 개의 독립된 라디오
        # 그룹으로 나눠 보여주고, script.js가 그 조합을 이 source_kind
        # 문자열로 합쳐서 보낸다 - 생략되면 하위 호환을 위해 기존 동작
        # (folder)을 그대로 유지한다.
        source_kind = str(item_data.get("source_kind", "folder")).strip().lower()
        valid_kinds = ("folder", "folder_local", "file", "file_local", "folder_extract", "file_extract")
        if source_kind not in valid_kinds:
            source_kind = "folder"

        # 안전장치: "folder"/"file"(원격) 모드인데 목적지가 누가 봐도 Windows
        # 로컬 경로(K:\... 또는 \\서버\...)면, 사용자가 목적지 종류를 잘못
        # 고른 것이 거의 확실하다 - rclone이 그 경로를 원격 경로 문자열로
        # 오인해서 엉뚱하게 동작하는(예: "libgdrive_oauth:K:다운로드/")
        # 사고가 실제로 있었기 때문에, 매번 사용자가 직접 라디오를 바꾸게
        # 시키는 대신 여기서 자동으로 로컬(그대로 다운로드) 모드로
        # 승격시킨다. 이 판별은 POSIX 절대경로('/data/...')에는 적용하지
        # 않는다 - rclone 원격 상대경로도 흔히 '/'로 시작해서 문자열만으로는
        # 구분이 안 되므로, 확실한 신호(드라이브 문자/UNC)가 있을 때만
        # 자동 전환한다. (압축 해제까지는 자동으로 판단하지 않는다 - 그건
        # "그대로 받을지, 풀어서 받을지"라는 별개의 선택이라 사용자가 직접
        # 골라야 한다.)
        auto_switched_to_local = False
        if source_kind == "folder" and looks_like_windows_local_path(dest_input):
            source_kind = "folder_local"
            auto_switched_to_local = True
        elif source_kind == "file" and looks_like_windows_local_path(dest_input):
            source_kind = "file_local"
            auto_switched_to_local = True

        is_file_source = source_kind in ("file", "file_local", "file_extract")  # 폴더가 아니라 파일 1개가 소스인 모드들
        is_local_dest = source_kind in ("folder_local", "file_local", "folder_extract", "file_extract")  # 목적지가 rclone 원격이 아니라 서버 로컬인 모드들

        if not source_url:
            if is_file_source:
                return False, "소스 파일 URL(또는 ID)을 입력해주세요."
            return False, "소스 폴더 URL(또는 ID)을 입력해주세요."
        if not dest_input:
            if is_local_dest:
                return False, "다운로드 목적지(로컬 절대경로)를 입력해주세요."
            return False, "목적지 경로를 입력해주세요."

        config = self._get_config(db_type)

        if is_local_dest:
            # 이 모드들의 목적지는 rclone 원격 경로가 아니라 "서버 로컬
            # 절대경로"이므로, 마운트 접두사 변환(to_rclone_relative_path)을
            # 적용하지 않고 사용자가 입력한 값을 그대로 넘긴다. 절대경로
            # 검증(os.path.isabs)은 logic.start_copy_job()에서 한 번 더 한다.
            # ("file" 모드에 이런 로컬 경로를 잘못 넣으면 rclone이 그걸 원격
            # 경로 문자열로 오인해 엉뚱하게 동작하므로, 반드시 목적지 종류를
            # 올바르게 골라야 한다 - 위 두 함수의 주석 참고.)
            dest_folder_name = dest_input
        else:
            mount_prefix = resolve_mount_prefix(config.get("MOUNT_PREFIX"), config.get("RCLONE_REMOTE"))
            dest_folder_name = to_rclone_relative_path(dest_input, mount_prefix)

        try:
            start_copy_job(
                rclone_path=config.get("RCLONE_PATH"),
                config_path=config.get("CONFIG_PATH"),
                rclone_remote=config.get("RCLONE_REMOTE"),
                source_folder_url=source_url,
                dest_folder_name=dest_folder_name,
                source_url_input=source_url,
                dest_input=dest_input,
                discord_webhook_url=config.get("DISCORD_WEBHOOK_URL"),
                transfers=config.get("RCLONE_TRANSFERS"),
                checkers=config.get("RCLONE_CHECKERS"),
                fast_list=str(config.get("RCLONE_FAST_LIST", "true")).lower() != "false",
                source_kind=source_kind,
                keep_archive_after_extract=bool(config.get("KEEP_ARCHIVE_AFTER_EXTRACT")),
            )
        except ConfigError as e:
            return False, str(e)
        except (ValueError, RuntimeError) as e:
            return False, str(e)

        kind_label = {
            "folder": "폴더",
            "folder_local": "폴더 로컬 다운로드",
            "file": "파일",
            "file_local": "로컬 다운로드",
            "folder_extract": "일괄 압축 해제",
            "file_extract": "압축 해제",
        }[source_kind]
        auto_switch_note = (
            " (목적지가 Windows 로컬 경로로 보여 자동으로 로컬 다운로드 모드로 전환했습니다.)"
            if auto_switched_to_local
            else ""
        )
        if source_kind == "folder_extract":
            return True, "폴더 안 압축파일 목록을 조회하고 있습니다. 진행 상황은 화면 하단 로그에서 확인하세요."
        if source_kind == "file_extract":
            return True, "다운로드 및 압축 해제를 시작했습니다. 진행 상황은 화면 하단 로그에서 확인하세요."
        if source_kind in ("file_local", "folder_local"):
            return True, f"로컬로 다운로드를 시작했습니다.{auto_switch_note} 진행 상황은 화면 하단 로그에서 확인하세요."
        if dest_folder_name != dest_input:
            return True, (
                f"{kind_label} 복사를 시작했습니다. "
                f"(입력하신 마운트 경로를 rclone 기준 경로 \"{dest_folder_name}\"로 변환했습니다)"
            )
        return True, f"{kind_label} 복사를 시작했습니다. 진행 상황은 화면 하단 로그에서 확인하세요."

    # ------------------------------------------------------------------
    # 풀페이지 뷰(index.html/script.js)가 주기적으로 폴링하는 데이터 소스
    # GET /api/media/dashboard/widgets/rclone_g2g_copy/data?type=<db_type>
    # ------------------------------------------------------------------
    def get_dashboard_data(self, db_type, limit=10):
        config = self._get_config(db_type)
        configured = bool(config.get("RCLONE_PATH") and config.get("CONFIG_PATH") and config.get("RCLONE_REMOTE"))
        mount_prefix = resolve_mount_prefix(config.get("MOUNT_PREFIX"), config.get("RCLONE_REMOTE"))

        job = get_last_job_status()

        return {
            "success": True,
            "config": {
                "configured": configured,
                "rclone_path": config.get("RCLONE_PATH"),
                "rclone_remote": config.get("RCLONE_REMOTE"),
                "mount_prefix": mount_prefix,
                "discord_notify_enabled": bool(config.get("DISCORD_WEBHOOK_URL")),
                # 설정 화면(settings.js)이 RCLONE_REMOTE를 풀다운으로 그릴 때 씀.
                # CONFIG_PATH가 아직 저장 전이거나 파일을 못 찾으면 빈 리스트.
                "available_remotes": list_rclone_remotes(config.get("CONFIG_PATH")),
                # 디버깅용 - job_state.json/job.log가 실제로 어느 경로에 있는지.
                # "강제 초기화해도 그대로임" 같은 문제 진단에 사용.
                "data_dir": get_data_dir_abs(),
            },
            "job": job,  # None이면 아직 시작한 job이 없다는 뜻
        }
