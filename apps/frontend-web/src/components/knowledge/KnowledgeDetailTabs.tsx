import type { KnowledgeDetailTab, KnowledgeItem } from "@/types/knowledge";

import {
  CitationsTab,
  DependenciesTab,
  IOTab,
  OverviewTab,
  RulesTab,
  ValidationTab,
} from "./KnowledgeDetailTabViews";

export function KnowledgeDetailTabPanels({
  item,
  activeTab,
}: {
  item: KnowledgeItem;
  activeTab: KnowledgeDetailTab;
}) {
  if (activeTab === "overview") return <OverviewTab item={item} />;
  if (activeTab === "rules") return <RulesTab item={item} />;
  if (activeTab === "io") return <IOTab item={item} />;
  if (activeTab === "dependencies") return <DependenciesTab item={item} />;
  if (activeTab === "validation") return <ValidationTab item={item} />;
  return <CitationsTab item={item} />;
}
