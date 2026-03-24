import { useEffect, useMemo, useState } from "react";

const defaultConfig = {
  pythonCommand: "python",
  backend: "transformers",
  modelId: "Qwen/Qwen3.5-4B",
  trustRemoteCode: true,
  responseTimeoutSeconds: 120,
  pollIntervalSeconds: 3,
  maxFollowUpMessages: 1,
  transcriptTurnLimit: 10,
  operatorGoal: "주문 CSV의 상품을 도매상에게 확인해 재고 여부를 기록합니다.",
  targetDescription: "카카오톡 채팅 상대는 도매상 또는 재고 확인 담당자입니다.",
  initialMessageTemplate: "안녕하세요. {item_name}{option_suffix}{quantity_suffix} 재고 있을까요?",
  systemPrompt:
    "답변이 명확한 재고 yes/no 가 아니면 사람 검토로 넘기고, 불필요하게 길게 말하지 마세요.",
  selectedOrdersCsv: "examples/orders_example.csv",
  selectedMappingCsv: ""
};

const settingGuide = {
  pythonCommand: {
    label: "Python command",
    description: "Next 서버가 백엔드 Python을 실행할 때 사용할 명령입니다.",
    reason: "가상환경 Python을 정확히 잡아야 `transformers`, `pywin32` 같은 패키지를 올바른 환경에서 읽습니다."
  },
  backend: {
    label: "Backend",
    description: "`transformers` 는 실제 로컬 LLM을 쓰고, `heuristic` 은 모델 없이 규칙 기반으로 동작합니다.",
    reason: "실전용과 I/O 디버깅용을 바로 전환할 수 있어야 합니다."
  },
  modelId: {
    label: "Model ID",
    description: "Hugging Face 모델 식별자입니다. 예: `Qwen/Qwen3.5-4B`",
    reason: "같은 UI에서 다른 오픈소스 모델로 바꿔 실험할 수 있어야 합니다."
  },
  responseTimeoutSeconds: {
    label: "Response timeout",
    description: "메시지를 보낸 뒤 상대 답장을 기다리는 최대 시간(초)입니다.",
    reason: "너무 짧으면 정상 대화도 놓치고, 너무 길면 작업이 과도하게 묶입니다."
  },
  pollIntervalSeconds: {
    label: "Poll interval",
    description: "새 카톡 답장을 몇 초 간격으로 확인할지 정합니다.",
    reason: "짧을수록 반응은 빠르지만 UI 자동화 부하가 늘어납니다."
  },
  maxFollowUpMessages: {
    label: "Max follow-up",
    description: "무응답일 때 자동 재문의할 최대 횟수입니다.",
    reason: "상대를 과하게 재촉하지 않으면서도 1회 정도는 자동 후속 확인을 할 수 있어야 합니다."
  },
  transcriptTurnLimit: {
    label: "Transcript turn limit",
    description: "모델이 최근 대화 몇 턴까지 메모리로 읽을지 정합니다.",
    reason: "너무 많으면 토큰이 낭비되고, 너무 적으면 문맥을 놓칩니다."
  },
  trustRemoteCode: {
    label: "trust_remote_code",
    description: "최신 모델 구조를 Hugging Face 원격 코드로 로드하도록 허용합니다.",
    reason: "Qwen 계열처럼 새 아키텍처가 공식 릴리스보다 빨리 나오는 경우 로딩을 살리기 위해 필요합니다."
  }
};

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function Section({ title, subtitle, children }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function Field({ title, description, reason, children, full = false, checkbox = false }) {
  return (
    <label className={`${full ? "full" : ""} ${checkbox ? "checkboxWrap" : ""}`.trim()}>
      <span className="fieldCopy">
        <strong>{title}</strong>
        <small>{description}</small>
        <small className="fieldWhy">왜 필요한가: {reason}</small>
      </span>
      {children}
    </label>
  );
}

export default function Home() {
  const [status, setStatus] = useState(null);
  const [files, setFiles] = useState({});
  const [jobs, setJobs] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [selectedJob, setSelectedJob] = useState(null);
  const [selectedFilePath, setSelectedFilePath] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [inputPreview, setInputPreview] = useState(null);
  const [outputPreview, setOutputPreview] = useState(null);
  const [config, setConfig] = useState(defaultConfig);
  const [configDirty, setConfigDirty] = useState(false);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  const fileOptions = useMemo(() => {
    const merge = [];
    Object.values(files).forEach((group) => {
      if (Array.isArray(group)) {
        merge.push(...group);
      }
    });
    return merge;
  }, [files]);

  async function refreshAll() {
    const [statusData, filesData, jobsData] = await Promise.all([
      fetchJson("/api/status"),
      fetchJson("/api/files"),
      fetchJson("/api/jobs")
    ]);
    const nextConfig = { ...defaultConfig, ...(statusData?.appState?.config || {}) };
    setStatus(statusData);
    setFiles(filesData);
    setJobs(jobsData.jobs || []);
    if (!configLoaded || !configDirty) {
      setConfig(nextConfig);
      setConfigLoaded(true);
    }
  }

  useEffect(() => {
    refreshAll().catch((error) => setNotice(error.message));
    const interval = setInterval(() => {
      refreshAll().catch(() => null);
      if (selectedJobId) {
        fetchJob(selectedJobId).catch(() => null);
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [selectedJobId]);

  useEffect(() => {
    const ordersPath = config.selectedOrdersCsv;
    if (!ordersPath) {
      setInputPreview(null);
      return;
    }
    fetchJson(`/api/file?path=${encodeURIComponent(ordersPath)}`)
      .then((data) => setInputPreview(data))
      .catch(() => setInputPreview(null));
  }, [config.selectedOrdersCsv]);

  useEffect(() => {
    const resultsPath = selectedJob?.job?.resultsCsv;
    if (!resultsPath) {
      setOutputPreview(null);
      return;
    }
    fetchJson(`/api/file?path=${encodeURIComponent(resultsPath)}`)
      .then((data) => setOutputPreview(data))
      .catch(() => setOutputPreview(null));
  }, [selectedJob?.job?.resultsCsv, selectedJob?.job?.updatedAt, selectedJob?.job?.status]);

  async function fetchJob(jobId) {
    const data = await fetchJson(`/api/job/${jobId}`);
    setSelectedJob(data);
    setSelectedJobId(jobId);
  }

  async function stopJob(jobId) {
    setBusy(true);
    setNotice("");
    try {
      await fetchJson(`/api/job/${jobId}/stop`, {
        method: "POST"
      });
      setNotice(`작업 ${jobId} 중지 요청을 보냈습니다.`);
      await refreshAll();
      if (selectedJobId === jobId) {
        await fetchJob(jobId);
      }
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function fetchFile(targetPath) {
    const data = await fetchJson(`/api/file?path=${encodeURIComponent(targetPath)}`);
    setSelectedFilePath(targetPath);
    setSelectedFile(data);
  }

  async function saveConfig() {
    setBusy(true);
    setNotice("");
    try {
      const saved = await fetchJson("/api/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config })
      });
      setConfig({ ...defaultConfig, ...(saved?.config || config) });
      setConfigDirty(false);
      setConfigLoaded(true);
      await refreshAll();
      setNotice("설정이 저장되었습니다.");
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function startJob() {
    setBusy(true);
    setNotice("");
    try {
      const result = await fetchJson("/api/start-agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config })
      });
      setSelectedJobId(result.jobId);
      setConfigDirty(false);
      setNotice(`작업 ${result.jobId} 이(가) 시작되었습니다.`);
      await refreshAll();
      await fetchJob(result.jobId);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function uploadCsv(event, target) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("target", target);
      formData.append("setSelected", "true");
      await fetchJson("/api/upload", {
        method: "POST",
        body: formData
      }).then(async (result) => {
        const key = target === "mapping" ? "selectedMappingCsv" : "selectedOrdersCsv";
        setConfig((current) => ({ ...current, [key]: result.relativePath }));
        setConfigLoaded(true);
        setConfigDirty(false);
        await fetchFile(result.relativePath);
      });
      await refreshAll();
      setNotice(`${target === "mapping" ? "매핑" : "주문"} CSV가 업로드되었습니다.`);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  function patchConfig(patch) {
    setConfig((current) => ({ ...current, ...patch }));
    setConfigDirty(true);
  }

  function restorePromptDefaults() {
    patchConfig({
      operatorGoal: defaultConfig.operatorGoal,
      targetDescription: defaultConfig.targetDescription,
      initialMessageTemplate: defaultConfig.initialMessageTemplate,
      systemPrompt: defaultConfig.systemPrompt
    });
    setNotice("새 작업용 기본 프롬프트를 다시 채웠습니다. 저장 후 적용됩니다.");
  }

  return (
    <main className="page">
      <header className="hero">
        <div>
          <div className="eyebrow">LLM For Kakao Front Ver</div>
          <h1>카카오톡 재고문의 작업실</h1>
          <p>
            CSV 업로드, 로컬 모델 상태, 작업 실행, 대화 로그와 요약, 작업 로그를 한 화면에서 관리합니다.
          </p>
        </div>
        <div className="heroNote">
          <strong>Assistant message</strong>
          <p>{status?.appState?.assistantMessage || "상태를 불러오는 중입니다."}</p>
        </div>
      </header>

      {notice ? <div className="notice">{notice}</div> : null}
      <div className="warningBox">
        현재 카카오 자동화는 전경 포커스와 클립보드에 의존합니다. 즉 완전한 백그라운드 자동화가 아니며,
        작업 중에는 카카오톡 창이 활성화될 수 있습니다. 한 번에 하나의 작업만 실행하세요.
      </div>

      <div className="grid two">
        <Section title="환경 상태" subtitle="현재 Python/모델/패키지 가용성">
          <div className="kv">
            <span>Python</span>
            <code>{status?.python?.executable || "-"}</code>
            <span>OS</span>
            <code>{status?.python?.platform || "-"}</code>
            <span>모델</span>
            <code>{status?.model?.selectedModelId || "-"}</code>
            <span>모델 캐시</span>
            <code>{status?.model?.downloaded ? "다운로드됨" : "첫 실행시 다운로드"}</code>
            <span>카카오 스크립트</span>
            <code>{status?.kakaoScriptExists ? "준비됨" : "없음"}</code>
            <span>활성 백엔드</span>
            <code>{status?.serverRuntime?.activeWorkers?.length || 0}개</code>
          </div>
          <div className="chips">
            {status?.packages
              ? Object.entries(status.packages).map(([name, available]) => (
                  <span className={`chip ${available ? "ok" : "bad"}`} key={name}>
                    {name}: {available ? "ok" : "missing"}
                  </span>
                ))
              : null}
          </div>
          {status?.serverRuntime?.activeWorkers?.length ? (
            <div className="list">
              {status.serverRuntime.activeWorkers.map((worker) => (
                <div className="listItem static" key={worker.jobId}>
                  <div>
                    <strong>{worker.jobId}</strong>
                    <span>PID {worker.pid}</span>
                  </div>
                  <small>{worker.modelId}</small>
                </div>
              ))}
            </div>
          ) : null}
        </Section>

        <Section title="작업 설정" subtitle="저장 후 그대로 실행할 수 있습니다.">
          <div className="formGrid">
            <Field {...settingGuide.pythonCommand}>
              <input
                value={config.pythonCommand || ""}
                onChange={(event) => patchConfig({ pythonCommand: event.target.value })}
              />
            </Field>
            <Field {...settingGuide.backend}>
              <select
                value={config.backend}
                onChange={(event) => patchConfig({ backend: event.target.value })}
              >
                <option value="transformers">transformers</option>
                <option value="heuristic">heuristic</option>
              </select>
            </Field>
            <Field {...settingGuide.modelId} full>
              <input
                value={config.modelId || ""}
                onChange={(event) => patchConfig({ modelId: event.target.value })}
              />
            </Field>
            <Field {...settingGuide.responseTimeoutSeconds}>
              <input
                type="number"
                value={config.responseTimeoutSeconds || 120}
                onChange={(event) =>
                  patchConfig({ responseTimeoutSeconds: Number(event.target.value) })
                }
              />
            </Field>
            <Field {...settingGuide.pollIntervalSeconds}>
              <input
                type="number"
                value={config.pollIntervalSeconds || 3}
                onChange={(event) =>
                  patchConfig({ pollIntervalSeconds: Number(event.target.value) })
                }
              />
            </Field>
            <Field {...settingGuide.maxFollowUpMessages}>
              <input
                type="number"
                value={config.maxFollowUpMessages || 1}
                onChange={(event) =>
                  patchConfig({ maxFollowUpMessages: Number(event.target.value) })
                }
              />
            </Field>
            <Field {...settingGuide.transcriptTurnLimit}>
              <input
                type="number"
                value={config.transcriptTurnLimit || 10}
                onChange={(event) =>
                  patchConfig({ transcriptTurnLimit: Number(event.target.value) })
                }
              />
            </Field>
            <Field {...settingGuide.trustRemoteCode} checkbox>
              <input
                type="checkbox"
                checked={Boolean(config.trustRemoteCode)}
                onChange={(event) =>
                  patchConfig({ trustRemoteCode: event.target.checked })
                }
              />
            </Field>
          </div>
          <div className="actions">
            <button disabled={busy} onClick={saveConfig}>
              설정 저장
            </button>
            <button className="primary" disabled={busy} onClick={startJob}>
              작업 시작
            </button>
          </div>
          {configDirty ? <div className="draftNotice">저장하지 않은 설정 변경이 있습니다.</div> : null}
        </Section>
      </div>

      <Section
        title="업무 역할 / 프롬프트"
        subtitle="누구에게 무엇을 시키는지, 모델이 어떤 기준으로 판단할지 설정합니다."
      >
        <div className="actions">
          <button disabled={busy} onClick={restorePromptDefaults}>
            새 작업용 기본 프롬프트 복원
          </button>
        </div>
        <div className="formGrid">
          <Field
            title="작업 목표"
            description="이 작업이 최종적으로 무엇을 해야 하는지 적습니다."
            reason="LLM이 재고 확인 대화에서 어디까지 자동 처리하고 언제 종료할지 판단하는 기준이 됩니다."
            full
          >
            <textarea
              rows={3}
              value={config.operatorGoal || ""}
              onChange={(event) => patchConfig({ operatorGoal: event.target.value })}
            />
          </Field>
          <Field
            title="문의 대상 설명"
            description="카카오톡 상대가 누구인지, 어떤 역할인지 설명합니다."
            reason="모델이 상대방을 고객이 아니라 도매상/재고 담당자로 해석해야 말투와 판단이 맞습니다."
            full
          >
            <textarea
              rows={3}
              value={config.targetDescription || ""}
              onChange={(event) => patchConfig({ targetDescription: event.target.value })}
            />
          </Field>
          <Field
            title="초기 문의 템플릿"
            description="첫 메시지를 어떤 문장 구조로 보낼지 정합니다. `{item_name}`, `{option_text}`, `{quantity}`, `{vendor_name}`, `{chatroom_name}`, `{option_suffix}`, `{quantity_suffix}` 를 쓸 수 있습니다."
            reason="실무 말투와 문의 형식을 사용자가 통제해야 실제 업무에 맞는 문장이 나갑니다."
            full
          >
            <textarea
              rows={3}
              value={config.initialMessageTemplate || ""}
              onChange={(event) =>
                patchConfig({ initialMessageTemplate: event.target.value })
              }
            />
          </Field>
          <Field
            title="모델 시스템 프롬프트"
            description="재고 판단 규칙, 금지할 행동, 사람 이관 기준 같은 추가 지시를 적습니다."
            reason="기본 정책만으로 부족한 도메인 규칙을 여기서 강하게 넣어야 합니다."
            full
          >
            <textarea
              rows={6}
              value={config.systemPrompt || ""}
              onChange={(event) => patchConfig({ systemPrompt: event.target.value })}
            />
          </Field>
        </div>
      </Section>

      <div className="grid two">
        <Section title="CSV 업로드 및 선택" subtitle="예제 또는 업로드 파일 중 하나를 선택하세요.">
          <div className="uploadRow">
            <label className="uploadButton">
              주문 CSV 업로드
              <input type="file" accept=".csv" onChange={(event) => uploadCsv(event, "orders")} />
            </label>
            <label className="uploadButton secondary">
              매핑 CSV 업로드
              <input type="file" accept=".csv" onChange={(event) => uploadCsv(event, "mapping")} />
            </label>
          </div>
          <div className="formGrid">
            <label className="full">
              Orders CSV
              <select
                value={config.selectedOrdersCsv || ""}
                onChange={(event) => patchConfig({ selectedOrdersCsv: event.target.value })}
              >
                <option value="">선택하세요</option>
                {fileOptions
                  .filter((file) => ["example", "upload"].includes(file.category))
                  .map((file) => (
                    <option key={file.relativePath} value={file.relativePath}>
                      {file.relativePath}
                    </option>
                  ))}
              </select>
            </label>
            <label className="full">
              Mapping CSV
              <select
                value={config.selectedMappingCsv || ""}
                onChange={(event) =>
                  patchConfig({ selectedMappingCsv: event.target.value })
                }
              >
                <option value="">사용 안 함</option>
                {fileOptions
                  .filter((file) => ["example", "upload"].includes(file.category))
                  .map((file) => (
                    <option key={file.relativePath} value={file.relativePath}>
                      {file.relativePath}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          <div className="list">
            {fileOptions
              .filter((file) => ["example", "upload"].includes(file.category))
              .map((file) => (
                <button
                  className="listItem"
                  key={file.relativePath}
                  onClick={() => fetchFile(file.relativePath)}
                >
                  <span>{file.relativePath}</span>
                  <small>{file.size} bytes</small>
                </button>
              ))}
          </div>
        </Section>

        <Section title="파일 뷰어" subtitle="CSV, 결과 파일, 대화 로그, 요약을 확인합니다.">
          {selectedFilePath ? (
            <>
              <div className="viewerTitle">{selectedFilePath}</div>
              {selectedFile?.encoding ? <div className="metaLine">decoded as {selectedFile.encoding}</div> : null}
              {selectedFile?.preview?.length ? (
                <pre className="viewer">{JSON.stringify(selectedFile.preview, null, 2)}</pre>
              ) : (
                <pre className="viewer">{selectedFile?.content || ""}</pre>
              )}
            </>
          ) : (
            <div className="empty">왼쪽 목록이나 아래 파일 목록에서 파일을 선택하세요.</div>
          )}
        </Section>
      </div>

      <div className="grid two">
        <Section title="입력 CSV 미리보기" subtitle="현재 선택된 주문 CSV가 맞는지 바로 확인합니다.">
          <div className="viewerTitle">{config.selectedOrdersCsv || "선택된 주문 CSV 없음"}</div>
          {inputPreview?.encoding ? <div className="metaLine">decoded as {inputPreview.encoding}</div> : null}
          {inputPreview?.preview?.length ? (
            <pre className="viewer">{JSON.stringify(inputPreview.preview, null, 2)}</pre>
          ) : (
            <div className="empty">주문 CSV를 선택하거나 업로드하면 여기에 즉시 표시됩니다.</div>
          )}
        </Section>

        <Section title="실시간 결과 CSV" subtitle="선택한 작업의 결과 CSV 누적 상태를 5초마다 갱신합니다.">
          <div className="viewerTitle">{selectedJob?.job?.resultsCsv || "선택한 작업 결과 CSV 없음"}</div>
          {selectedJob?.resultsPreviewEncoding ? (
            <div className="metaLine">decoded as {selectedJob.resultsPreviewEncoding}</div>
          ) : outputPreview?.encoding ? (
            <div className="metaLine">decoded as {outputPreview.encoding}</div>
          ) : null}
          {selectedJob?.resultsPreviewCsv?.length ? (
            <pre className="viewer">{JSON.stringify(selectedJob.resultsPreviewCsv, null, 2)}</pre>
          ) : outputPreview?.preview?.length ? (
            <pre className="viewer">{JSON.stringify(outputPreview.preview, null, 2)}</pre>
          ) : (
            <div className="empty">작업을 시작하고 작업 목록에서 선택하면 결과 CSV가 여기에 바로 누적됩니다.</div>
          )}
        </Section>
      </div>

      <div className="grid two">
        <Section title="작업 목록" subtitle="최근 작업 상태와 에러를 확인합니다.">
          <div className="list">
            {jobs.map((job) => (
              <button
                className={`listItem ${selectedJobId === job.jobId ? "active" : ""}`}
                key={job.jobId}
                onClick={() => fetchJob(job.jobId)}
              >
                <div>
                  <strong>{job.jobId}</strong>
                  <span>{job.status}</span>
                </div>
                <small>{job.currentStep || job.modelId || "-"}</small>
              </button>
            ))}
            {!jobs.length ? <div className="empty">아직 실행한 작업이 없습니다.</div> : null}
          </div>
        </Section>

        <Section title="작업 상세 / 로그" subtitle="선택한 작업의 로그와 결과 미리보기">
          {selectedJob?.job ? (
            <>
              <div className="kv">
                <span>상태</span>
                <code>{selectedJob.job.status}</code>
                <span>현재 단계</span>
                <code>{selectedJob.job.currentStep || "-"}</code>
                <span>PID</span>
                <code>{selectedJob.job.pid || "-"}</code>
                <span>주문 CSV</span>
                <code>{selectedJob.job.ordersCsv || "-"}</code>
                <span>결과 CSV</span>
                <code>{selectedJob.job.resultsCsv || "-"}</code>
                <span>현재 주문</span>
                <code>{selectedJob.job.currentItemName || "-"}</code>
                <span>현재 상대</span>
                <code>{selectedJob.job.currentChatroomName || "-"}</code>
                <span>작업 목표</span>
                <code>{selectedJob.job.operatorGoal || config.operatorGoal || "-"}</code>
                <span>문의 대상</span>
                <code>{selectedJob.job.targetDescription || config.targetDescription || "-"}</code>
                <span>Assistant</span>
                <code>{selectedJob.job.assistantMessage || "-"}</code>
              </div>
              {["queued", "running", "stopping"].includes(selectedJob.job.status) ? (
                <div className="actions">
                  <button
                    className="danger"
                    disabled={busy}
                    onClick={() => stopJob(selectedJob.job.jobId)}
                  >
                    작업 중지
                  </button>
                </div>
              ) : null}
              {selectedJob.job.progressEvents?.length ? (
                <pre className="viewer">
                  {JSON.stringify(selectedJob.job.progressEvents.slice(-20), null, 2)}
                </pre>
              ) : null}
              {selectedJob.resultsPreviewCsv?.length ? (
                <pre className="viewer">{JSON.stringify(selectedJob.resultsPreviewCsv, null, 2)}</pre>
              ) : null}
              <pre className="viewer">{selectedJob.logTail || "로그가 아직 없습니다."}</pre>
            </>
          ) : (
            <div className="empty">작업을 선택하면 상세 로그가 표시됩니다.</div>
          )}
        </Section>
      </div>

      <Section title="결과 / 대화 로그 파일" subtitle="작업이 만든 CSV, transcript, summary 파일을 바로 엽니다.">
        <div className="fileGrid">
          {["results", "transcripts", "jobs"].map((category) => (
            <div key={category}>
              <h3>{category}</h3>
              <div className="list compact">
                {(files[category] || []).map((file) => (
                  <button
                    className="listItem"
                    key={file.relativePath}
                    onClick={() => fetchFile(file.relativePath)}
                  >
                    <span>{file.relativePath}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Section>
    </main>
  );
}
