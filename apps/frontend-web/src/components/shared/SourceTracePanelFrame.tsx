import type { ComponentProps } from "react";
import { SourceTraceCard } from "./SourceTraceCard";

type SourceTracePanelFrameProps = Omit<ComponentProps<typeof SourceTraceCard>, "sources"> & {
  sourceTrace?: ComponentProps<typeof SourceTraceCard>["sources"];
};

export function SourceTracePanelFrame({ sourceTrace = [], ...props }: SourceTracePanelFrameProps) {
  return <SourceTraceCard {...props} sources={sourceTrace} />;
}
