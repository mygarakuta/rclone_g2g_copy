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

변경 이력(이번 수정):
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
)


class RcloneG2gCopyProvider(BaseMetadataProvider):
    id = "rclone_g2g_copy"
    name = "폴더 복사 (rclone G2G)"
    is_searchable = False

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

        if not source_url:
            return False, "소스 폴더 URL(또는 ID)을 입력해주세요."
        if not dest_input:
            return False, "목적지 경로를 입력해주세요."

        config = self._get_config(db_type)
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
            )
        except ConfigError as e:
            return False, str(e)
        except (ValueError, RuntimeError) as e:
            return False, str(e)

        if dest_folder_name != dest_input:
            return True, f"복사를 시작했습니다. (입력하신 마운트 경로를 rclone 기준 경로 \"{dest_folder_name}\"로 변환했습니다)"
        return True, "복사를 시작했습니다. 진행 상황은 화면 하단 로그에서 확인하세요."

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
