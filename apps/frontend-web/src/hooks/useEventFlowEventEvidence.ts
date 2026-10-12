import { useEffect, useState } from "react";
import {
  fetchEventFlowEventImpact,
  fetchEventFlowMarketReaction,
} from "@/adapters/eventFlow";
import type {
  EventFlowEvidenceIdentity,
  EventFlowImpactReadModel,
  EventFlowMarketReactionReadModel,
} from "@/types/event-flow";
import { resolveEventEvidenceIdentity } from "@/components/event-flow/eventEvidenceFormat";

export interface EventFlowEventEvidenceState {
  impact: EventFlowImpactReadModel | null;
  marketReaction: EventFlowMarketReactionReadModel | null;
  impactIdentity: EventFlowEvidenceIdentity;
  marketReactionIdentity: EventFlowEvidenceIdentity;
  impactLoading: boolean;
  marketReactionLoading: boolean;
  isLoading: boolean;
  impactError: Error | null;
  marketReactionError: Error | null;
  refetch: () => void;
}

function evidenceRequestKey(eventId: string | null, reloadToken: number): string {
  return JSON.stringify([eventId, reloadToken]);
}

/** Read-only event evidence. Each endpoint is isolated so a partial response
 * remains visible without converting the other endpoint into a fake success. */
export function useEventFlowEventEvidence(eventId: string | null): EventFlowEventEvidenceState {
  const [impact, setImpact] = useState<EventFlowImpactReadModel | null>(null);
  const [marketReaction, setMarketReaction] = useState<EventFlowMarketReactionReadModel | null>(null);
  const [impactIdentity, setImpactIdentity] = useState<EventFlowEvidenceIdentity>("unverified");
  const [marketReactionIdentity, setMarketReactionIdentity] = useState<EventFlowEvidenceIdentity>("unverified");
  const [impactError, setImpactError] = useState<Error | null>(null);
  const [marketReactionError, setMarketReactionError] = useState<Error | null>(null);
  const [impactLoading, setImpactLoading] = useState(Boolean(eventId));
  const [marketReactionLoading, setMarketReactionLoading] = useState(Boolean(eventId));
  const [isLoading, setIsLoading] = useState(Boolean(eventId));
  const [reloadToken, setReloadToken] = useState(0);
  const requestKey = evidenceRequestKey(eventId, reloadToken);
  const [stateRequestKey, setStateRequestKey] = useState(requestKey);
  const stateBelongsToRequest = stateRequestKey === requestKey;

  useEffect(() => {
    let cancelled = false;
    setStateRequestKey(requestKey);
    if (!eventId) {
      setImpact(null);
      setMarketReaction(null);
      setImpactIdentity("unverified");
      setMarketReactionIdentity("unverified");
      setImpactError(null);
      setMarketReactionError(null);
      setImpactLoading(false);
      setMarketReactionLoading(false);
      setIsLoading(false);
      return () => { cancelled = true; };
    }

    setIsLoading(true);
    setImpact(null);
    setMarketReaction(null);
    setImpactIdentity("unverified");
    setMarketReactionIdentity("unverified");
    setImpactError(null);
    setMarketReactionError(null);
    setImpactLoading(true);
    setMarketReactionLoading(true);

    let impactSettled = false;
    let reactionSettled = false;
    const finishLoading = () => {
      if (impactSettled && reactionSettled && !cancelled) setIsLoading(false);
    };

    void fetchEventFlowEventImpact(eventId)
      .then((value) => {
        if (cancelled) return;
        const identity = resolveEventEvidenceIdentity(eventId, value.event_id);
        setImpactIdentity(identity);
        if (identity === "mismatch") {
          setImpactError(new Error(`影响分析 event_id 与路由事件不一致：${value.event_id ?? "未提供"}`));
        } else {
          setImpact(value);
        }
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setImpactError(reason instanceof Error ? reason : new Error("事件影响分析读取失败"));
      })
      .finally(() => {
        impactSettled = true;
        if (cancelled) return;
        setImpactLoading(false);
        finishLoading();
      });

    void fetchEventFlowMarketReaction(eventId)
      .then((value) => {
        if (cancelled) return;
        const identity = resolveEventEvidenceIdentity(eventId, value.event_id);
        setMarketReactionIdentity(identity);
        if (identity === "mismatch") {
          setMarketReactionError(new Error(`行情反应 event_id 与路由事件不一致：${value.event_id ?? "未提供"}`));
        } else {
          setMarketReaction(value);
        }
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setMarketReactionError(reason instanceof Error ? reason : new Error("事件行情验证读取失败"));
      })
      .finally(() => {
        reactionSettled = true;
        if (cancelled) return;
        setMarketReactionLoading(false);
        finishLoading();
      });

    return () => { cancelled = true; };
  }, [eventId, reloadToken, requestKey]);

  const visibleState = stateBelongsToRequest
    ? {
      impact,
      marketReaction,
      impactIdentity,
      marketReactionIdentity,
      impactLoading,
      marketReactionLoading,
      isLoading,
      impactError,
      marketReactionError,
    }
    : {
      impact: null,
      marketReaction: null,
      impactIdentity: "unverified" as EventFlowEvidenceIdentity,
      marketReactionIdentity: "unverified" as EventFlowEvidenceIdentity,
      impactLoading: Boolean(eventId),
      marketReactionLoading: Boolean(eventId),
      isLoading: Boolean(eventId),
      impactError: null,
      marketReactionError: null,
    };

  return {
    ...visibleState,
    refetch: () => setReloadToken((value) => value + 1),
  };
}

export default useEventFlowEventEvidence;
