let state,
  view = "data",
  answer = null,
  sourceLedger = null;
const $ = (s) => document.querySelector(s),
  esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
const fmt = (v) =>
  v === null || v === undefined
    ? "—"
    : Number(v).toLocaleString("en-US", { maximumFractionDigits: 4 });
const issueLabel = (i) =>
  ({
    duplicate_submission: "같은 사업장·기간·에너지 중복",
    missing_value: "값 누락 · 원자료 확인 필요",
    unsupported_unit: "지원하지 않는 단위",
    negative_value: "음수 사용량 · 원자료 확인",
    stale_period: "보고 기간 불일치",
    invalid_number: "유효한 숫자 형식 필요",
    missing_source: "원자료 참조 필요",
    unsupported_precision: "소수점 9자리 이내 필요",
    out_of_range: "시연 지원 범위 초과",
  })[i.code] || i.message;
async function api(path, body) {
  const r = await fetch(
    "/api/" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!r.ok) {
    let e = await r.json();
    const err = Error(
      e.code === "stale_snapshot"
        ? "다른 화면에서 데이터·문서가 바뀌었습니다. 내용을 다시 확인하세요."
        : e.error || e.message || "요청을 확인해 주세요.",
    );
    err.code = e.code;
    throw err;
  }
  return r.json();
}
function toast(t) {
  $("#toast").textContent = t;
  $("#toast").style.display = "block";
  setTimeout(() => ($("#toast").style.display = "none"), 3600);
}
function render() {
  document
    .querySelectorAll(".nav")
    .forEach((n) => n.classList.toggle("active", n.dataset.view === view));
  const valid = state.summary.unresolved_count === 0,
    current = state.review.status === "current";
  $("#step1").classList.toggle("done", valid);
  $("#step3").classList.toggle("done", current);
  $("#step4").classList.toggle("done", current);
  $("#gate").className = "gate" + (current ? " ready" : "");
  $("#gate").textContent = current
    ? "✓ 담당자 확인 완료 · 인계 가능"
    : valid
      ? "담당자 확인 대기"
      : `검수 보류 · ${state.summary.invalid_count}건 확인 필요`;
  $("#main").innerHTML =
    view === "data"
      ? dataView()
      : view === "guide"
        ? guideView()
        : reviewView();
  bindView();
}
function metrics() {
  return `<div class="metrics"><div class="metric"><label>제출 기록 / 집계 제외 포함</label><strong>${state.records.length}<small>건</small></strong><span class="aux">3개 국가 · 합성 시연</span></div><div class="metric alert"><label>현재 확인 필요</label><strong>${state.summary.invalid_count}<small>건</small></strong><span class="aux">미해결 기록</span></div><div class="metric"><label>검수 통과 / 제외</label><strong>${state.summary.valid_count}<small> / ${state.summary.excluded_count}건</small></strong></div><div class="metric"><label>유효 제출값 부분합 · 최종 보고값 아님</label><strong>${fmt(state.summary.normalized_kwh)}<small> kWh</small></strong></div></div>`;
}
function dataView() {
  return (
    metrics() +
    `<section class="panel"><div class="panel-head"><h2>사업장 제출값 검수</h2><span>2026.09 · 전력 사용량 · 원자료 확인 후 수정</span></div><table><thead><tr><th>제출 사업장 / 언어</th><th>기간</th><th>원자료 값</th><th>kWh 변환</th><th>검수 상태</th><th>확인 사유</th><th></th></tr></thead><tbody>${state.records.map((r) => `<tr class="${r.status === "invalid" ? "selected" : ""}"><td><span class="site">${esc(r.site)}</span><span class="sub">${esc(r.id)} · ${esc(r.country)} · ${esc(r.lang.toUpperCase())}</span></td><td class="mono">${esc(r.period)}</td><td class="mono">${r.value === null ? "값 누락" : esc(r.value)} ${esc(r.unit)}</td><td class="mono">${fmt(r.normalized_kwh)}</td><td><span class="pill ${r.status}">${{ valid: "통과", invalid: "확인 필요", excluded: "집계 제외" }[r.status]}</span></td><td class="issue">${r.issues.map((i) => esc(issueLabel(i))).join("<br>") || (r.excluded ? esc(r.exclusion_reason) : '<span class="success">검수 규칙 충족</span>')}</td><td><button class="row-edit" data-edit="${esc(r.id)}">수정 →</button></td></tr>`).join("")}</tbody></table></section><div class="bottom-grid"><section class="panel note-panel"><p class="eyebrow">RULES FIRST</p><h3>누락된 숫자를 0으로 채우지 않습니다.</h3><p>같은 사업장·기간·에너지의 중복은 함께 보류합니다.<br>값과 단위를 확인한 기록만 부분합에 포함합니다.</p><div class="compact-rules"><span>Decimal 단위 변환</span><span>보고 기간 대조</span><span>중복·음수·누락 검사</span></div></section><section class="panel note-panel"><p class="eyebrow">UNIT NORMALIZATION</p><h3>단위가 달라도, 계산 근거는 같습니다.</h3><div class="equation">1 MWh = 1,000 kWh</div><div class="notice">온실가스 배출량 환산은 포함하지 않습니다.<br>사업장·연도별 배출계수와 산정 경계를 검증한 뒤 확장합니다.</div></section></div>`
  );
}
function guideView() {
  return `<div class="guide-grid"><section class="panel ask"><p class="eyebrow">GROUNDED DRAFT</p><h2>문서에서 찾고, 초안의 근거를 봅니다.</h2><label for="question">업무 질문</label><textarea id="question">${esc(answer?.question || "How should I handle missing energy readings?")}</textarea><div class="ask-controls"><select id="language" aria-label="응답 문서 언어"><option value="en" ${answer?.language === "en" ? "selected" : ""}>English</option><option value="ko" ${answer?.language === "ko" ? "selected" : ""}>한국어</option><option value="vi" ${answer?.language === "vi" ? "selected" : ""}>Tiếng Việt</option></select><button id="ask" class="primary">근거 검색 + AI 초안</button><button id="retrieve" class="secondary">검색만</button></div><div class="notice">현재 개정 문서만 검색합니다. 자료가 없거나 인용이 맞지 않으면 답변을 보류합니다.</div>${answer ? `<div class="answer"><div class="answer-head"><h3>${answer.generated ? "AI 업무 안내 초안" : answer.abstained ? "답변 보류" : "원문 검색 결과"}</h3><span class="pill ${answer.abstained ? "invalid" : ""}">${answer.generated ? "인용 대조 통과" : answer.abstained ? "근거 부족" : "검색 완료"}</span></div><div class="answer-text">${esc(answer.answer)}</div><div class="model-detail">${esc(answer.mode)}${answer.model ? " · " + esc(answer.model) : ""}${answer.generation_ms ? " · " + fmt(answer.generation_ms / 1000) + "s" : ""}</div>${answer.generated ? '<p class="hint">원문 인용의 일치 여부를 검사했습니다. 초안 전체의 의미·업무 적합성은 담당자가 확인해야 합니다.</p>' : ""}${answer.generation_error ? '<p class="hint error">' + esc(answer.generation_error) + "</p>" : ""}</div>` : '<div class="empty">질문을 입력하면 사용한 문서와 개정번호를 함께 표시합니다.<br>AI 초안이 데이터의 검수·확인을 대신하지 않습니다.</div>'}</section><section class="panel evidence-panel"><p class="eyebrow">SOURCE TRACE</p><h2>초안 옆에, 인용 원문을 놓습니다.</h2>${answer?.citations?.length ? answer.citations.map((c) => `<article class="doc"><div class="doc-heading"><b>${esc(c.title)}</b><span>${esc(c.language.toUpperCase())} · CURRENT</span></div><div class="doc-id">${esc(c.doc_id)} · rev ${esc(c.revision)}</div><blockquote class="quote">${esc(c.quote)}</blockquote><div class="digest">SHA-256 ${esc(c.source_digest)}</div></article>`).join("") : '<div class="empty">원문 ID · 개정번호 · 인용 문장 · 해시<br>검색 결과를 재확인할 수 있도록 같이 남깁니다.</div>'}</section></div><div class="guide-floor"><div><b>검색 → 생성 → 인용 대조 → 사람의 판단</b><span class="muted">수치 계산과 보고서 확인은 규칙 기반 경로에서 별도로 처리합니다.</span></div><div><b>한국어 · 영어 · 베트남어 문서</b><span class="muted">합성 SOP로 경로를 시연합니다. 번역 품질·전사 운영은 검증하지 않았습니다.</span></div></div>`;
}
function reviewView() {
  let current = state.review.status === "current",
    clean = state.summary.unresolved_count === 0;
  return `<div class="review-grid"><section class="panel review-box"><p class="eyebrow">HUMAN CHECKPOINT</p><h2>확인한 버전만 인계합니다.</h2><div class="review-status ${current ? "success" : ""}">${current ? "담당자 확인 완료" : state.review.status === "stale" ? "데이터 변경 · 재확인 필요" : "담당자 확인 대기"}</div><p>${current ? esc(state.review.reviewer) + " · " + esc(state.review.note) : clean ? "검수 오류를 해소했습니다. 원자료와 제외 사유를 대조한 담당자가 현재 버전을 확인합니다." : "미해결 기록이 남아 있습니다. 데이터 검수 화면에서 수정한 뒤 현재 버전을 확인해 주세요."}</p><label for="reviewer">확인 담당자 · 시연값</label><input id="reviewer" value="Demo reviewer"><label for="review-note">확인 메모</label><textarea id="review-note" rows="2">원자료 대조 및 중복 제외 사유를 확인했습니다.</textarea><div class="actions"><button id="review" class="primary" ${!clean ? "disabled" : ""}>현재 버전 확인</button><button id="export" class="secondary" ${!current ? "disabled" : ""}>CSV 내보내기</button></div><p class="hint">로컬 시연용 확인입니다. 로그인·전자결재·실제 승인 권한은 연결하지 않았습니다.</p></section><section class="panel"><div class="panel-head"><h2>수정·확인 기록</h2><span>SQLite에 저장 · 최근 기록 · UTC</span></div>${
    state.audit.length
      ? state.audit
          .slice()
          .sort((a, b) => b.id - a.id)
          .slice(0, 7)
          .map(
            (a) =>
              `<article class="audit-entry"><div class="audit-time">${esc((a.at || "").slice(11, 19))}<br>#${esc(a.id)}</div><div><div class="audit-head">${esc(actionLabel(a.action))}${a.record_id ? " · " + esc(a.record_id) : ""}</div><p>${esc(a.action === "human_review_demo" ? "현재 데이터·문서 해시에 확인 기록을 연결했습니다." : describeChange(a))}</p></div></article>`,
          )
          .join("")
      : '<div class="empty">제출값을 수정하거나 현재 버전을 확인하면<br>변경 전·후 내용과 시각을 기록합니다.</div>'
  }</section></div><section class="panel digest-band"><div><label>현재 데이터 SHA-256</label><code>${esc(state.digests.data)}</code></div><div><label>현재 문서 묶음 SHA-256</label><code>${esc(state.digests.corpus)}</code></div></section><div class="guide-floor"><div><b>데이터 또는 문서 변경 → 이전 확인 만료</b><span class="muted">검수 통과만으로 보고서를 내보내지 않습니다. 같은 버전에 대한 담당자 확인이 필요합니다.</span></div><div><b>내보내기: ${current ? "허용" : "보류"}</b><span class="muted">유효 제출값 ${fmt(state.summary.normalized_kwh)} kWh · 제외 ${state.summary.excluded_count}건</span></div></div>`;
}
function actionLabel(a) {
  return (
    {
      repair: "제출값 수정",
      review: "현재 버전 확인",
      reset: "합성 시연 초기화",
      exclude: "중복 집계 제외",
      human_review_demo: "현재 버전 확인",
      reset_demo: "합성 시연 초기화",
    }[a] || a
  );
}
function describeChange(a) {
  const b = a.before || {},
    n = a.after || {};
  return n.excluded
    ? `집계 제외: ${n.exclusion_reason || n.reason || ""}`
    : `${b.value ?? "누락"} ${b.unit || ""} → ${n.value ?? "누락"} ${n.unit || ""} · ${n.period || ""}`;
}
function bindView() {
  document
    .querySelectorAll("[data-edit]")
    .forEach((n) => (n.onclick = () => edit(n.dataset.edit)));
  if (view === "guide") {
    const ask = async (generate) => {
      let q = $("#question").value,
        language = $("#language").value;
      $("#ask").disabled = $("#retrieve").disabled = true;
      $("#ask").textContent = "원문 대조 중…";
      try {
        answer = {
          ...(await api("ask", { question: q, language, generate })),
          question: q,
          language,
        };
        render();
      } catch (e) {
        toast(e.message);
        render();
      }
    };
    $("#ask").onclick = () => ask(true);
    $("#retrieve").onclick = () => ask(false);
  }
  if (view === "review") {
    $("#review").onclick = async () => {
      try {
        state = await api("review", {
          reviewer: $("#reviewer").value,
          note: $("#review-note").value,
          digests: state.digests,
        });
        render();
        toast("현재 버전에 확인 기록을 저장했습니다.");
      } catch (e) {
        if (e.code === "stale_snapshot") {
          state = await api("state");
          render();
        }
        toast(e.message);
      }
    };
    $("#export").onclick = () => {
      window.location.href = "/api/export";
      toast("확인된 버전의 CSV를 내보냅니다.");
    };
  }
}
function edit(id) {
  let r = state.records.find((x) => x.id === id);
  let source = sourceLedger?.records.find((x) => x.source_doc === r.source_doc);
  $("#source-confirmation").textContent = source
    ? "합성 원자료 " +
      source.source_doc +
      " · " +
      source.period +
      " · " +
      source.value +
      " " +
      source.unit +
      (source.duplicate_of ? " · 중복 원본 " + source.duplicate_of : "")
    : "원자료 참조: " + r.source_doc;
  $("#edit-title").textContent = r.site + " · " + r.id;
  $("#edit-id").value = id;
  $("#edit-value").value = r.value ?? "";
  $("#edit-unit").value = r.unit;
  $("#edit-period").value = r.period;
  $("#edit-excluded").checked = r.excluded;
  $("#edit-reason").value = r.exclusion_reason || "";
  $("#edit-dialog").showModal();
}
$("#cancel-edit").onclick = () => $("#edit-dialog").close();
$("#edit-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    state = await api("repair", {
      id: $("#edit-id").value,
      value: $("#edit-value").value || null,
      unit: $("#edit-unit").value,
      period: $("#edit-period").value,
      excluded: $("#edit-excluded").checked,
      reason: $("#edit-reason").value,
    });
    $("#edit-dialog").close();
    render();
    toast("수정 기록을 저장했습니다. 현재 버전을 다시 확인해 주세요.");
  } catch (e) {
    toast(e.message);
  }
};
document.querySelectorAll(".nav").forEach(
  (n) =>
    (n.onclick = () => {
      view = n.dataset.view;
      render();
    }),
);
$("#reset").onclick = async () => {
  try {
    state = await api("reset", {});
    answer = null;
    render();
    toast("합성 시연을 초기 상태로 되돌렸습니다.");
  } catch (e) {
    toast(e.message);
  }
};
Promise.all([api("state"), fetch("/source-ledger.json").then((r) => r.json())])
  .then(([s, ledger]) => {
    state = s;
    sourceLedger = ledger;
    render();
  })
  .catch((e) => {
    $("#main").innerHTML =
      `<div class="panel empty error">서버에 연결하지 못했습니다. ${esc(e.message)}</div>`;
  });
