import { BookOpen } from "lucide-react";
import { ContextPanelSectionHeader } from "@/components/shared/ContextPanel";
import { KNOWLEDGE_TAGS } from "./rightPanelStaticData";
import {
  StaticSubsectionTitle,
  StaticTag,
} from "./RightPanelStaticPrimitives";
import {
  FINAL_SECTION_STYLE,
  TAG_LIST_STYLE,
} from "./rightPanelStaticSectionStyles";

export function KnowledgeTagsSection() {
  return (
    <div>
      <StaticSubsectionTitle icon={BookOpen} title="知识" />
      <div className="flex flex-wrap" style={TAG_LIST_STYLE}>
        {KNOWLEDGE_TAGS.map((tag) => (
          <StaticTag key={tag}>{tag}</StaticTag>
        ))}
      </div>
    </div>
  );
}

export function ReportsKnowledgeSection() {
  return (
    <div style={FINAL_SECTION_STYLE}>
      <KnowledgeTagsSection />
    </div>
  );
}
