// rclone_g2g_copy 플러그인 카테고리탭 풀페이지 스크립트
// scan_scheduler의 script.js와 동일하게 new Function('pluginId', 'container', ...)로
// 실행되므로 import 없이 전역 API + 인자로 받는 pluginId/container만 사용합니다.

(function () {
  const LOG_PREFIX = '[rclone_g2g_copy]';
  console.log(LOG_PREFIX, '0/2 카테고리탭 UI 로드됨.');

  // scan_scheduler와 동일하게, 이 플러그인도 특정 db_type(라이브러리 스코프)에
  // 종속되지 않는 전역 유틸리티라 'general'로 고정해서 보냅니다.
  const DB_TYPE = 'general';

  let pollTimer = null;
  let renderedLineCount = 0;
  let lastJobStatus = null; // running | success | error | cancelled | null(아직 없음)

  const banner = container.querySelector('[data-role="config-banner"]');
  const sourceKindFolderRadio = container.querySelector('[data-role="source-kind-folder"]');
  const sourceKindFileRadio = container.querySelector('[data-role="source-kind-file"]');
  const sourceKindExtractRadio = container.querySelector('[data-role="source-kind-extract"]');
  const sourceLabel = container.querySelector('[data-role="source-label"]');
  const sourceKindHint = container.querySelector('[data-role="source-kind-hint"]');
  const sourceInput = container.querySelector('[data-role="source-url"]');
  const destLabel = container.querySelector('[data-role="dest-label"]');
  const destInput = container.querySelector('[data-role="dest-folder"]');
  const destPreview = container.querySelector('[data-role="dest-preview"]');
  const startBtn = container.querySelector('[data-role="start-btn"]');
  const cancelBtn = container.querySelector('[data-role="cancel-btn"]');
  const resetBtn = container.querySelector('[data-role="reset-btn"]');
  const statusText = container.querySelector('[data-role="status-text"]');
  const logBox = container.querySelector('[data-role="log-box"]');
  const logDest = container.querySelector('[data-role="log-dest"]');
  const progressWrap = container.querySelector('[data-role="progress-wrap"]');
  const progressFill = container.querySelector('[data-role="progress-fill"]');
  const progressPercent = container.querySelector('[data-role="progress-percent"]');
  const progressSummary = container.querySelector('[data-role="progress-summary"]');
  const progressDetail = container.querySelector('[data-role="progress-detail"]');

  let mountPrefix = '';
  let inputsPrefilled = false;

  // 폴링 주기. 이 프레임워크는 요청마다 플러그인 모듈을 새로 로드하는
  // 구조라(README 참고), 폴링이 잦을수록 서버 부하가 커진다. 그래서:
  //  - 시작 직후 잠깐만(START_BURST_MS) 빠르게(FAST_MS) 확인해서 반응성을 살리고,
  //  - 그 뒤로는 느리게(SLOW_MS)만 확인한다.
  //  - 브라우저 탭이 보이지 않을 때는(document.hidden) 폴링을 완전히 멈추고,
  //    다시 보이게 되면 즉시 한 번 확인 후 재개한다.
  const POLL_FAST_MS = 2000;
  const POLL_SLOW_MS = 8000;
  const POLL_FAST_WINDOW_MS = 20000;
  let pollStartedAt = 0;

  const STATUS_LABEL = {
    success: '완료',
    cancelled: '사용자가 중단함',
  };

  // logic.py의 to_rclone_relative_path()와 동일한 규칙: 입력이 마운트
  // 접두사로 시작하면 그 부분을 잘라내 rclone 기준 상대 경로로 바꾼다.
  // (서버에서도 동일하게 다시 한 번 변환하므로, 여기는 미리보기 전용)
  function toRcloneRelativePath(path, prefix) {
    const p = (path || '').trim();
    if (!p) return p;
    const normPath = p.replace(/\/+$/, '');
    const normPrefix = (prefix || '').trim().replace(/\/+$/, '');
    if (normPrefix && normPath.startsWith(normPrefix)) {
      let remainder = normPath.slice(normPrefix.length);
      if (!remainder.startsWith('/')) remainder = '/' + remainder;
      return remainder || '/';
    }
    return p;
  }

  // ==================================================================
  // 소스 종류(폴더 전체 복사 / 개별 압축파일 1개 그대로 복사 / 폴더 안
  // 압축파일 일괄 다운로드+압축해제) 토글
  // logic.py의 get_folder_id()/get_file_id()와 동일한 URL 패턴을 JS로도
  // 복제해서, 사용자가 URL을 붙여넣으면 라디오를 자동으로 맞춰준다
  // (수동으로 직접 바꿀 수도 있음 - 최종 판단은 항상 서버가 다시 검증).
  //
  // "folder_extract" 모드는 다른 두 모드와 "목적지 경로"의 의미 자체가 다르다 -
  // folder/file은 rclone 원격 경로("remote:path")이고, folder_extract는 서버의
  // 로컬 절대경로다(마운트 경로 변환을 적용하면 안 됨). 그래서 destPreview도
  // 이 모드에서는 rclone 변환 미리보기 대신 안내 문구로 바뀐다.
  //
  // folder/folder_extract는 둘 다 소스가 "폴더"라는 점에서 같은 부류다 -
  // isFolderKind()로 이 둘을 묶어서 자동 감지 로직에 쓴다.
  // ==================================================================
  const SOURCE_KIND_META = {
    folder: {
      sourceLabel: '소스 폴더 (구글 드라이브 URL 또는 폴더 ID)',
      sourcePlaceholder: 'https://drive.google.com/drive/folders/xxxxxxxxxxxx',
      sourceHint: '폴더 공유 링크(.../drive/folders/폴더ID) 또는 폴더 ID를 입력하세요. 폴더 안의 파일 전체가 복사됩니다.',
      destLabel: '목적지 경로 (도커/호스트 마운트 경로 또는 rclone 기준 상대 경로 둘 다 입력 가능)',
      destPlaceholder: '/mnt/zeeps_member/zeepsmember/공유_폴더명 또는 /zeepsmember/공유_폴더명',
      startLabel: '복사 시작',
      showRcloneDestPreview: true,
    },
    file: {
      sourceLabel: '소스 파일 (구글 드라이브 URL 또는 파일 ID) — 압축파일 1개',
      sourcePlaceholder: 'https://drive.google.com/file/d/xxxxxxxxxxxx/view',
      sourceHint: '파일 공유 링크(.../file/d/파일ID/view) 또는 파일 ID를 입력하세요. 원본 파일명 그대로 목적지 폴더에 저장됩니다.',
      destLabel: '목적지 경로 (도커/호스트 마운트 경로 또는 rclone 기준 상대 경로 둘 다 입력 가능)',
      destPlaceholder: '/mnt/zeeps_member/zeepsmember/공유_폴더명 또는 /zeepsmember/공유_폴더명',
      startLabel: '복사 시작',
      showRcloneDestPreview: true,
    },
    folder_extract: {
      sourceLabel: '소스 폴더 (구글 드라이브 URL 또는 폴더 ID) — 폴더 안의 압축파일 전체',
      sourcePlaceholder: 'https://drive.google.com/drive/folders/xxxxxxxxxxxx',
      sourceHint: '폴더 공유 링크(.../drive/folders/폴더ID) 또는 폴더 ID를 입력하세요. 폴더 안(하위 폴더 포함)의 zip/cbz 파일을 모두 찾아 각각 다운로드 후 압축을 해제합니다.',
      destLabel: '압축 해제 목적지 (서버의 로컬 절대경로 — rclone 경로가 아닙니다)',
      destPlaceholder: '/data/comics/시리즈명',
      startLabel: '전체 다운로드 + 압축 해제 시작',
      showRcloneDestPreview: false,
    },
  };

  function isFolderKind(kind) {
    return kind === 'folder' || kind === 'folder_extract';
  }

  function getSourceKind() {
    if (sourceKindExtractRadio && sourceKindExtractRadio.checked) return 'folder_extract';
    if (sourceKindFileRadio && sourceKindFileRadio.checked) return 'file';
    return 'folder';
  }

  function setSourceKind(kind) {
    const normalized = SOURCE_KIND_META[kind] ? kind : 'folder';
    if (sourceKindFolderRadio) sourceKindFolderRadio.checked = normalized === 'folder';
    if (sourceKindFileRadio) sourceKindFileRadio.checked = normalized === 'file';
    if (sourceKindExtractRadio) sourceKindExtractRadio.checked = normalized === 'folder_extract';
    updateSourceKindUI();
  }

  function updateSourceKindUI() {
    const meta = SOURCE_KIND_META[getSourceKind()];
    if (sourceLabel) sourceLabel.textContent = meta.sourceLabel;
    sourceInput.placeholder = meta.sourcePlaceholder;
    if (sourceKindHint) sourceKindHint.textContent = meta.sourceHint;
    if (destLabel) destLabel.textContent = meta.destLabel;
    destInput.placeholder = meta.destPlaceholder;
    if (startBtn) startBtn.textContent = meta.startLabel;
    updateDestPreview(); // 목적지 의미가 바뀌었으니 미리보기도 다시 계산
  }

  function updateDestPreview() {
    const meta = SOURCE_KIND_META[getSourceKind()];
    const raw = (destInput.value || '').trim();

    if (!meta.showRcloneDestPreview) {
      // folder_extract 모드: rclone 경로 변환이 아니라, "이 로컬 폴더 아래에
      // 원본 폴더 구조 그대로 압축이 풀린다"는 사실을 안내한다.
      destPreview.textContent = raw ? `이 서버 로컬 경로 아래에 원본 폴더 구조대로 압축이 해제됩니다: ${raw}` : '';
      destPreview.removeAttribute('data-state');
      return;
    }

    if (!raw) {
      destPreview.textContent = '';
      destPreview.removeAttribute('data-state');
      return;
    }
    const converted = toRcloneRelativePath(raw, mountPrefix);
    if (converted !== raw) {
      destPreview.textContent = `→ rclone 기준 경로: ${converted}`;
      destPreview.setAttribute('data-state', 'converted');
    } else {
      destPreview.textContent = `rclone 기준 경로로 그대로 사용됩니다: ${raw}`;
      destPreview.removeAttribute('data-state');
    }
  }

  destInput.addEventListener('input', updateDestPreview);

  // URL 패턴으로 폴더/파일을 자동 감지해 라디오를 맞춰준다 (편의 기능 -
  // 사용자가 직접 라디오를 눌러 덮어쓸 수도 있음).
  //
  // folder/folder_extract는 둘 다 "폴더" URL을 받으므로, 폴더 URL을
  // 붙여넣었을 때 이미 folder_extract가 선택되어 있다면 그대로 둔다(사용자의
  // 명시적 선택을 folder로 되돌리지 않음) - 파일 계열('file')이 선택되어
  // 있을 때만 기본값인 'folder'로 전환한다. 파일 URL을 붙여넣었을 때는
  // 반대로 폴더 계열이 선택되어 있으면 'file'로 전환한다.
  function autoDetectSourceKindFromUrl() {
    const url = (sourceInput.value || '').trim();
    if (!url) return;
    const current = getSourceKind();
    if (/\/folders\//.test(url)) {
      if (!isFolderKind(current)) {
        setSourceKind('folder');
      }
    } else if (/\/file\/d\//.test(url) || /[?&]id=/.test(url)) {
      if (isFolderKind(current)) {
        setSourceKind('file');
      }
    }
    // 슬래시 없는 순수 ID만 붙여넣은 경우는 폴더/파일 어느 쪽인지 URL만으로
    // 알 수 없으므로 자동 변경하지 않는다 - 사용자가 라디오로 직접 선택.
  }

  if (sourceKindFolderRadio) sourceKindFolderRadio.addEventListener('change', updateSourceKindUI);
  if (sourceKindFileRadio) sourceKindFileRadio.addEventListener('change', updateSourceKindUI);
  if (sourceKindExtractRadio) sourceKindExtractRadio.addEventListener('change', updateSourceKindUI);
  sourceInput.addEventListener('input', autoDetectSourceKindFromUrl);
  updateSourceKindUI(); // 초기 라벨/플레이스홀더 세팅

  function renderConfigBanner(cfg) {
    if (!cfg) return;
    mountPrefix = cfg.mount_prefix || '';
    updateDestPreview(); // mountPrefix가 새로 반영됐으니 미리보기도 다시 계산

    // job_state.json/job.log가 실제로 어느 경로에 있는지는 배너 툴팁(마우스
    // 오버)과 콘솔에 남겨둔다 - "강제 초기화해도 그대로임" 같은 문제를
    // 진단할 때, 앱이 실제로 쓰는 경로를 바로 확인할 수 있게.
    if (cfg.data_dir) {
      banner.title = `데이터 경로: ${cfg.data_dir}`;
      if (!renderConfigBanner._loggedDataDir) {
        renderConfigBanner._loggedDataDir = true;
        console.log(LOG_PREFIX, '데이터 경로:', cfg.data_dir);
      }
    }

    if (cfg.configured) {
      banner.setAttribute('data-state', 'ok');
      const discordNote = cfg.discord_notify_enabled ? ' · 디스코드 알림 켜짐' : '';
      banner.textContent =
        `설정 완료 · remote: ${cfg.rclone_remote} · rclone: ${cfg.rclone_path} · 마운트 접두사: ${cfg.mount_prefix}${discordNote}`;
    } else {
      banner.setAttribute('data-state', 'missing');
      banner.textContent =
        'RCLONE_PATH / CONFIG_PATH / RCLONE_REMOTE가 아직 설정되지 않았습니다. 설정 화면에서 먼저 저장해주세요.';
    }
  }

  function appendLines(lines) {
    // 이전엔 새 줄마다 logBox.textContent += line 을 반복했는데, 줄이
    // 많아지면(수백~수천 줄) 매번 전체 문자열을 새로 복사하게 되어(사실상
    // O(n^2)) 화면 전환/새로고침 직후 첫 렌더링이 눈에 띄게 느렸다.
    // 서버가 최근 최대 30줄만 내려주므로(logic.py의 _MAX_RETURN_LINES),
    // 매 폴링마다 배열을 한 번에 join해서 통째로 다시 그려도 충분히 가볍다.
    if (!lines) return;

    const nearBottom = logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 40;
    logBox.textContent = lines.join('\n');
    renderedLineCount = lines.length;
    if (nearBottom) {
      logBox.scrollTop = logBox.scrollHeight;
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function scheduleNextPoll() {
    stopPolling();
    if (document.hidden) return; // 탭이 안 보이면 예약하지 않음 - visibilitychange가 재개시킴
    const elapsed = Date.now() - pollStartedAt;
    const interval = elapsed < POLL_FAST_WINDOW_MS ? POLL_FAST_MS : POLL_SLOW_MS;
    pollTimer = setTimeout(poll, interval);
  }

  function setRunningUI(isRunning) {
    startBtn.disabled = isRunning;
    cancelBtn.hidden = !isRunning;
    cancelBtn.disabled = false;
    // "중단"이 눌러도 안 먹히거나 실제로는 안 도는데 running으로 남아있는
    // 꼬인 상황을 위한 탈출구 - 실행 중일 때 같이 보여준다.
    resetBtn.hidden = !isRunning;
    // 실행 중에는 소스 종류를 바꿔도 이미 시작된 job에는 반영되지 않으므로
    // 혼동을 막기 위해 라디오를 잠근다.
    if (sourceKindFolderRadio) sourceKindFolderRadio.disabled = isRunning;
    if (sourceKindFileRadio) sourceKindFileRadio.disabled = isRunning;
    if (sourceKindExtractRadio) sourceKindExtractRadio.disabled = isRunning;
  }

  function formatProgressDetail(progress) {
    const parts = [];
    if (progress.current_file) parts.push(progress.current_file);
    if (progress.transferred && progress.total) parts.push(`${progress.transferred} / ${progress.total}`);
    if (progress.speed) parts.push(progress.speed);
    if (progress.eta) parts.push(`ETA ${progress.eta}`);
    return parts.join(' · ');
  }

  // "전체 진행률"로 보여줄 하나의 퍼센트를 고른다. rclone은 바이트 기준과
  // 파일개수 기준, 두 가지 퍼센트를 따로 찍는데 파일 크기가 제각각이면 서로
  // 다르게 움직인다. 바이트 기준(percent, 전체 데이터량 대비)이 더 정확한
  // "전체" 지표라 우선하고, 아직 그 줄이 안 나왔으면(막 시작 직후) 파일개수
  // 기준(files_percent)으로 대체해서 진행률 바가 먼저 움직이는 걸 보여준다.
  function overallPercent(progress) {
    if (typeof progress.percent === 'number') return progress.percent;
    if (typeof progress.files_percent === 'number') return progress.files_percent;
    return null;
  }

  function renderProgress(job) {
    const progress = (job && job.progress) || null;
    const hasData = progress && Object.keys(progress).length > 0;

    if (!hasData) {
      if (job && job.status === 'running') {
        progressWrap.hidden = false;
        progressFill.style.width = '0%';
        progressPercent.textContent = '0%';
        progressSummary.textContent = '';
        progressDetail.textContent = '진행률 계산 중...';
      } else {
        progressWrap.hidden = true;
      }
      return;
    }

    progressWrap.hidden = false;
    const percent = overallPercent(progress);
    const clamped = Math.max(0, Math.min(100, percent || 0));
    progressFill.style.width = `${clamped}%`;
    progressPercent.textContent = percent === null ? '-' : `${clamped}%`;
    progressSummary.textContent = progress.files_total
      ? `${progress.files_done || 0} / ${progress.files_total} 파일`
      : '';
    progressDetail.textContent = formatProgressDetail(progress);
  }

  function renderJob(job) {
    if (!job) {
      logDest.textContent = '';
      setRunningUI(false);
      progressWrap.hidden = true;
      return;
    }

    // 화면을 새로 열었을 때(또는 새로고침) 이미 진행 중이거나 방금 끝난 job이
    // 있으면, 사용자가 입력했던 원본 값(변환 전)을 그대로 입력창에 복원한다.
    // 딱 한 번만 채우고, 이후에는 사용자가 직접 수정한 값을 건드리지 않는다.
    if (!inputsPrefilled) {
      inputsPrefilled = true;
      if (job.source_kind) {
        setSourceKind(job.source_kind);
      }
      if (job.source_url_input && !sourceInput.value) {
        sourceInput.value = job.source_url_input;
      }
      if (job.dest_input && !destInput.value) {
        destInput.value = job.dest_input;
      }
      updateDestPreview();
    }
    const kindPrefix =
      job.source_kind === 'folder_extract' ? '[일괄압축해제] ' : job.source_kind === 'file' ? '[파일] ' : job.source_kind === 'folder' ? '[폴더] ' : '';
    logDest.textContent = job.dest_path ? `${kindPrefix}→ ${job.dest_path}` : '';
    appendLines(job.lines);
    renderProgress(job); // 진행률은 상태가 바뀌지 않아도(계속 'running') 매 폴링마다 갱신되어야 함

    if (job.status === 'running') {
      setRunningUI(true);
    }

    if (job.status === lastJobStatus) return;
    lastJobStatus = job.status;

    if (job.status === 'running') {
      statusText.textContent = '복사 진행 중...';
    } else if (job.status === 'success' || job.status === 'cancelled') {
      statusText.textContent = STATUS_LABEL[job.status];
      setRunningUI(false);
      stopPolling();
    } else if (job.status === 'error') {
      statusText.textContent = `오류로 종료됨 (종료 코드: ${job.returncode})`;
      setRunningUI(false);
      stopPolling();
    }
  }

  // ==================================================================
  // 데이터 로딩 (설정 상태 + 최근 job 상태) - scan_scheduler의
  // fetchSchedules()와 동일한 엔드포인트 규약
  // ==================================================================
  function poll() {
    const params = new URLSearchParams({ type: DB_TYPE, limit: '1' });
    const url = `/api/media/dashboard/widgets/${pluginId}/data?${params.toString()}`;

    fetch(url)
      .then((res) => res.json())
      .then((data) => {
        if (!data.success) {
          statusText.textContent = `상태 조회 실패: ${data.error || '알 수 없는 오류'}`;
          console.warn(LOG_PREFIX, '데이터 조회 실패:', data.error);
          return;
        }
        renderConfigBanner(data.config);
        renderJob(data.job);

        if (data.job && data.job.status === 'running') {
          if (!pollStartedAt) pollStartedAt = Date.now();
          scheduleNextPoll();
        } else {
          pollStartedAt = 0;
          stopPolling();
        }
      })
      .catch((err) => {
        statusText.textContent = `상태 조회 실패: ${err}`;
        console.error(LOG_PREFIX, '요청 실패:', err);
        // 네트워크 오류로도 폴링이 끊기지 않도록, 진행 중이었다면 계속 재시도
        if (pollStartedAt) scheduleNextPoll();
      });
  }

  // 탭이 백그라운드로 가면 폴링을 멈추고, 다시 보이면 즉시 한 번 확인 후
  // 필요하면 재개한다 - 안 보고 있는 동안의 불필요한 부하를 없앤다.
  function onVisibilityChange() {
    if (document.hidden) {
      stopPolling();
    } else {
      poll();
    }
  }
  document.addEventListener('visibilitychange', onVisibilityChange);

  // ==================================================================
  // 액션 호출 공통부 - scan_scheduler의 saveEdit()과 동일한 호출 규약:
  // POST /api/media/books/0/apply-metadata,
  // body { type, source: pluginId, item_data }, 응답은 data.success / data.error
  // ==================================================================
  function callApply(itemData) {
    return fetch('/api/media/books/0/apply-metadata', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: DB_TYPE, source: pluginId, item_data: itemData }),
    }).then((res) => res.json());
  }

  function startCopy() {
    const sourceKind = getSourceKind();
    const sourceUrl = (sourceInput.value || '').trim();
    const destFolder = (destInput.value || '').trim();

    if (!sourceUrl) {
      statusText.textContent =
        sourceKind === 'file' ? '소스 파일 URL(또는 ID)을 입력해주세요.' : '소스 폴더 URL(또는 ID)을 입력해주세요.';
      return;
    }
    if (!destFolder) {
      statusText.textContent =
        sourceKind === 'folder_extract' ? '압축 해제 목적지(로컬 절대경로)를 입력해주세요.' : '목적지 경로를 입력해주세요.';
      return;
    }

    startBtn.disabled = true;
    statusText.textContent = '요청을 보내는 중...';
    renderedLineCount = 0;
    lastJobStatus = null;
    logBox.textContent = '';
    logDest.textContent = '';
    progressWrap.hidden = true;
    progressFill.style.width = '0%';
    progressPercent.textContent = '0%';
    progressSummary.textContent = '';
    progressDetail.textContent = '';

    callApply({
      action: 'start_copy',
      source_url: sourceUrl,
      dest_folder_name: destFolder,
      source_kind: sourceKind,
    })
      .then((data) => {
        if (!data || !data.success) {
          const message = (data && (data.error || data.message)) || '요청이 거부되었습니다.';
          statusText.textContent = message;
          startBtn.disabled = false;
          // "이미 실행 중" 류의 거부라면, 실제로는 꼬여서 안 풀리는 상황일 수
          // 있으니 강제 초기화 링크를 보여준다.
          if (message.indexOf('이미 실행 중') !== -1) {
            resetBtn.hidden = false;
          }
          return;
        }
        statusText.textContent = data.message || '복사를 시작했습니다.';
        console.log(LOG_PREFIX, '복사 시작 요청 성공');
        pollStartedAt = Date.now(); // 시작 직후 잠깐은 빠르게 확인
        poll();
      })
      .catch((err) => {
        statusText.textContent = `시작 실패: ${err}`;
        startBtn.disabled = false;
        console.error(LOG_PREFIX, '요청 실패:', err);
      });
  }

  function cancelCopy() {
    if (!window.confirm('진행 중인 복사를 중단할까요? 이미 복사된 파일은 그대로 남습니다.')) {
      return;
    }
    cancelBtn.disabled = true;
    statusText.textContent = '중단 요청 중...';

    callApply({ action: 'cancel_copy' })
      .then((data) => {
        if (!data || !data.success) {
          statusText.textContent = (data && (data.error || data.message)) || '중단 요청이 거부되었습니다.';
          cancelBtn.disabled = false;
          return;
        }
        statusText.textContent = data.message || '중단을 요청했습니다.';
        console.log(LOG_PREFIX, '중단 요청 성공');
        // 중단 처리가 실제로 끝나는 걸 빨리 반영하도록 잠깐 빠른 주기로 전환
        pollStartedAt = Date.now();
        poll();
      })
      .catch((err) => {
        statusText.textContent = `중단 요청 실패: ${err}`;
        cancelBtn.disabled = false;
        console.error(LOG_PREFIX, '요청 실패:', err);
      });
  }

  function resetJob() {
    if (
      !window.confirm(
        '작업 상태를 강제로 초기화할까요?\n\n' +
          '"중단"이 안 먹히거나, 실제로는 끝났는데 화면에 계속 "실행 중"으로 남아있을 때만 사용하세요.'
      )
    ) {
      return;
    }
    resetBtn.disabled = true;
    statusText.textContent = '초기화 중...';

    callApply({ action: 'reset_job' })
      .then((data) => {
        if (!data || !data.success) {
          statusText.textContent = (data && (data.error || data.message)) || '초기화가 거부되었습니다.';
          resetBtn.disabled = false;
          return;
        }
        statusText.textContent = data.message || '초기화되었습니다.';
        console.log(LOG_PREFIX, '강제 초기화 완료');
        lastJobStatus = null;
        renderedLineCount = 0;
        setRunningUI(false);
        logBox.textContent = '';
        logDest.textContent = '';
        progressWrap.hidden = true;
        stopPolling();
        pollStartedAt = 0;
      })
      .catch((err) => {
        statusText.textContent = `초기화 실패: ${err}`;
        resetBtn.disabled = false;
        console.error(LOG_PREFIX, '요청 실패:', err);
      });
  }

  startBtn.addEventListener('click', startCopy);
  cancelBtn.addEventListener('click', cancelCopy);
  resetBtn.addEventListener('click', resetJob);

  // 탭이 언마운트될 때 폴링 타이머가 남지 않도록 정리 레지스트리에 등록
  // (plugin_hub 작업 때 확인된 window.__bookOasisViewerCleanups 관례)
  window.__bookOasisViewerCleanups = window.__bookOasisViewerCleanups || {};
  window.__bookOasisViewerCleanups[pluginId] = function () {
    stopPolling();
    document.removeEventListener('visibilitychange', onVisibilityChange);
  };

  poll();
  console.log(LOG_PREFIX, '1/2 초기 상태 조회 요청 시작');
})();
