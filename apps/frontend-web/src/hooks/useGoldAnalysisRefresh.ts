import { useCallback, useEffect, useRef, useState } from "react";
import { fetchGoldAnalysisPreflight, fetchGoldAnalysisTask, readGoldAnalysisTask, rememberGoldAnalysisTask, startGoldAnalysis } from "@/adapters/goldWorkspace";
import type { GoldAnalysisTask } from "@/types/gold-workspace";

type Phase = "idle" | "checking" | "running" | "blocked" | "uncertain" | "complete" | "failed";
export function useGoldAnalysisRefresh(onCompleted: (taskId: string) => Promise<boolean>) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [task, setTask] = useState<GoldAnalysisTask | null>(null);
  const [lookupError, setLookupError] = useState(false);
  const mounted = useRef(false);
  const starting = useRef(false);
  const completed = useRef(onCompleted);
  completed.current = onCompleted;

  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    const saved = readGoldAnalysisTask();
    if (saved && saved !== "uncertain") { setTaskId(saved); setPhase("running"); setMessage("恢复跟踪上次分析任务。"); }
    else {
      if (saved === "uncertain") { setPhase("uncertain"); setMessage("上次启动结果尚未确认，请重新核对任务。"); }
      void fetchGoldAnalysisPreflight().then(preflight => {
        if (!cancelled && preflight.active_task_id) {
          rememberGoldAnalysisTask(preflight.active_task_id);
          setTaskId(preflight.active_task_id); setPhase("running"); setMessage("正在跟踪已有分析任务。");
        }
      }).catch(() => undefined);
    }
    return () => { mounted.current = false; cancelled = true; };
  }, []);

  const start = useCallback(async () => {
    if (starting.current || phase === "running" || phase === "checking") return;
    starting.current = true;
    setPhase("checking"); setMessage("正在检查数据源与已有分析任务。");
    try {
      const result = await startGoldAnalysis();
      if (mounted.current) { setPhase(result.phase); setMessage(result.message); setTaskId(result.task_id); setTask(null); }
    } catch {
      if (mounted.current) { setPhase("blocked"); setMessage("无法核验分析启动条件，请恢复服务连接后重试。"); }
    } finally { starting.current = false; }
  }, [phase]);

  const clearUncertain = useCallback(() => {
    if (phase !== "uncertain" || starting.current) return;
    rememberGoldAnalysisTask(null);
    setPhase("idle"); setMessage("已解除本次待核对状态。点击更新数据并分析时会重新检查服务和已有任务。");
  }, [phase]);

  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const result = await fetchGoldAnalysisTask(taskId);
        if (cancelled) return;
        setTask(result); setLookupError(false);
        if (result.status === "success") {
          setMessage("流程已完成，正在读取并核验本次研究结果。");
          const ready = await completed.current(taskId);
          if (cancelled) return;
          rememberGoldAnalysisTask(null); setPhase("complete");
          setMessage(ready ? "本次研究已生成并通过读取核验；策略仍须满足各项条件。" : "流程已完成，本次完整研究尚未核验通过。已保留可读结果，请查看研究缺口。");
          return;
        }
        if (!["pending", "running"].includes(result.status)) {
          rememberGoldAnalysisTask(null); setPhase("failed");
          setMessage("本次分析未完整完成，保留此前研究。请查看失败步骤，恢复后再更新。");
          return;
        }
        setPhase("running");
      } catch {
        if (cancelled) return;
        setLookupError(true); setMessage("任务状态读取失败，仍保留并跟踪原任务，不重新启动。");
      }
      if (!cancelled) timer = window.setTimeout(poll, 5_000);
    };
    void poll();
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); };
  }, [taskId]);
  return { phase, message, task, taskId, lookupError, start, clearUncertain, busy: phase === "checking" || phase === "running" };
}
