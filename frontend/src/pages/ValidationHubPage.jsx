import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import {
  FlaskConical, GitCompare, Beaker, Trophy, ChevronRight, FlaskRound,
  ChevronDown,
} from "lucide-react";

import PairwisePage from "./PairwisePage";
import SciPostPage from "./SciPostPage";
import SciPostPairwiseSection from "./SciPostPairwiseSection";
import QeiosPairwiseSection from "./QeiosPairwiseSection";
import PairwiseAgreementSection from "./PairwiseAgreementSection";
import SummarizerComparisonSection from "./SummarizerComparisonSection";
import SummaryBiasSection from "./SummaryBiasSection";
import { DatasetView } from "./ValidationPage";

const API = process.env.REACT_APP_BACKEND_URL;

function groupDatasets(datasets) {
  const groups = {};
  for (const ds of datasets) {
    const name = ds.name || "";
    let source;
    if (name.startsWith("ICLR ")) source = "ICLR";
    else if (name.startsWith("eLife ")) source = "eLife";
    else if (name.startsWith("MIDL ")) source = "MIDL";
    else if (name.startsWith("Qeios ")) source = "Qeios";
    else if (name.startsWith("PeerRead ")) source = "PeerRead";
    else if (name.startsWith("F1000")) source = "F1000";
    else if (name.startsWith("ResearchHub")) source = "ResearchHub";
    else source = "Other";
    if (!groups[source]) groups[source] = [];
    groups[source].push(ds);
  }
  return groups;
}

function CollapsibleGroup({ label, children, defaultOpen = false, icon: Icon }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-1.5 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
      >
        {Icon && <Icon className="h-3 w-3" />}
        <span className="flex-1 text-left">{label}</span>
        <ChevronDown className={`h-3 w-3 transition-transform ${open ? "" : "-rotate-90"}`} />
      </button>
      {open && <div className="space-y-0.5 mt-0.5">{children}</div>}
    </div>
  );
}

function NavItem({ item, selected, onSelect }) {
  return (
    <button
      onClick={() => onSelect(item.id)}
      className={`w-full text-left px-3 py-1.5 rounded-lg text-sm transition-colors flex items-center justify-between ${
        selected === item.id
          ? "bg-accent/10 text-accent font-medium border border-accent/20"
          : "text-muted-foreground hover:bg-secondary/30 hover:text-foreground border border-transparent"
      }`}
      data-testid={`nav-${item.id}`}
    >
      <div>
        <div className="text-[11px] font-medium">{item.label}</div>
        {item.sub && <div className="text-[9px] opacity-60 mt-0.5">{item.sub}</div>}
      </div>
      {selected === item.id && <ChevronRight className="h-3 w-3 shrink-0" />}
    </button>
  );
}

function SourceGroup({ source, items, selected, onSelect, defaultOpen }) {
  return (
    <CollapsibleGroup label={source} defaultOpen={defaultOpen}>
      {items.map(item => (
        <NavItem key={item.id} item={item} selected={selected} onSelect={onSelect} />
      ))}
    </CollapsibleGroup>
  );
}

export default function ValidationHubPage() {
  const [selected, setSelected] = useState("pw-qeios");
  const [datasets, setDatasets] = useState([]);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchDatasets = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/validation/datasets`);
      setDatasets(r.data.datasets || []);
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { fetchDatasets(); }, [fetchDatasets]);

  const pairwiseDatasets = datasets;
  const tournamentGroups = groupDatasets(datasets);
  const pairwiseGroups = groupDatasets(datasets);

  // Auto-open the group containing the selected item
  const selectedTournamentSource = Object.entries(tournamentGroups).find(
    ([, items]) => items.some(ds => `t-${ds.dataset_id}` === selected)
  )?.[0];
  const selectedPairwiseSource = Object.entries(pairwiseGroups).find(
    ([, items]) => items.some(ds => `pw-h2h-${ds.dataset_id}` === selected)
  )?.[0];

  const activeDataset = datasets.find(ds => selected === `t-${ds.dataset_id}`);

  const sectionMeta = {
    "pw-qeios": { title: "Pairwise — Qeios", desc: "Head-to-head AI comparison using Qeios open peer review data. 3 AI models, majority-vote agreement with human expert." },
    "pw-scipost": { title: "Pairwise — SciPost", desc: "Per-dimension head-to-head comparison (validity, significance, originality, clarity) using SciPost peer review data." },
    "si-scipost": { title: "Single-item — SciPost", desc: "AI rates each paper on 4 dimensions (1-6 scale), compared against human referee ratings." },
    "exp-summary-bias": { title: "Summary Bias — Biomolecules", desc: "Does the LLM that wrote the summary bias the judge? 3 judges x 3 summary sources x 200 matches." },
    "exp-summary-bias-econ": { title: "Summary Bias — Economics", desc: "Does the LLM that wrote the summary bias the judge? 3 judges x 3 summary sources x 200 matches." },
    "exp-summary-bias-phys": { title: "Summary Bias — Comp Physics", desc: "Does the LLM that wrote the summary bias the judge? 3 judges x 3 summary sources x 200 matches." },
  };
  pairwiseDatasets.forEach(ds => {
    sectionMeta[`pw-h2h-${ds.dataset_id}`] = {
      title: `Pairwise — ${ds.name}`,
      desc: `How often do different input formats and AI models agree with human expert judgments?`,
    };
  });
  if (activeDataset) {
    sectionMeta[selected] = { title: `Tournament — ${activeDataset.name}`, desc: activeDataset.description || activeDataset.source || "" };
  }
  const meta = sectionMeta[selected] || { title: "", desc: "" };

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-7xl py-6 md:py-10">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <FlaskConical className="h-5 w-5 text-accent" />
          <h1 className="font-heading text-2xl font-semibold" data-testid="validation-hub-title">Validation</h1>
        </div>
        <p className="text-sm text-muted-foreground max-w-3xl">
          Does AI agree with human peer reviewers? Three methods, multiple datasets — pairwise comparison, single-item rating, and full tournament ranking.
        </p>
      </div>

      <div className="flex gap-5">
        <nav className="w-56 shrink-0 space-y-3 max-h-[calc(100vh-120px)] overflow-y-auto" data-testid="validation-sidebar">
          {/* Pairwise */}
          <CollapsibleGroup label="Pairwise" icon={GitCompare} defaultOpen={selected.startsWith("pw-")}>
            <NavItem item={{ id: "pw-qeios", label: "Qeios" }} selected={selected} onSelect={setSelected} />
            <NavItem item={{ id: "pw-scipost", label: "SciPost" }} selected={selected} onSelect={setSelected} />
            {Object.entries(pairwiseGroups).map(([source, items]) => (
              <SourceGroup
                key={`pw-${source}`}
                source={source}
                items={items.map(ds => ({ id: `pw-h2h-${ds.dataset_id}`, label: ds.name.replace(`${source} `, ""), sub: `${ds.papers} papers` }))}
                selected={selected}
                onSelect={setSelected}
                defaultOpen={selectedPairwiseSource === source}
              />
            ))}
          </CollapsibleGroup>

          {/* Single-item */}
          <CollapsibleGroup label="Single-item" icon={Beaker} defaultOpen={selected === "si-scipost"}>
            <NavItem item={{ id: "si-scipost", label: "SciPost" }} selected={selected} onSelect={setSelected} />
          </CollapsibleGroup>

          {/* Tournament */}
          <CollapsibleGroup label="Tournament" icon={Trophy} defaultOpen={selected.startsWith("t-")}>
            {Object.entries(tournamentGroups).map(([source, items]) => (
              <SourceGroup
                key={`t-${source}`}
                source={source}
                items={items.map(ds => ({ id: `t-${ds.dataset_id}`, label: ds.name.replace(`${source} `, ""), sub: `${ds.papers} papers` }))}
                selected={selected}
                onSelect={setSelected}
                defaultOpen={selectedTournamentSource === source}
              />
            ))}
          </CollapsibleGroup>

          {/* Experiments */}
          <CollapsibleGroup label="Experiments" icon={FlaskRound} defaultOpen={selected.startsWith("exp-")}>
            <NavItem item={{ id: "exp-summarizer-ab", label: "Opus 4.5 vs 4.6", sub: "Summarizer A/B test" }} selected={selected} onSelect={setSelected} />
            <NavItem item={{ id: "exp-summary-bias", label: "Summary Bias", sub: "Biomolecules" }} selected={selected} onSelect={setSelected} />
            <NavItem item={{ id: "exp-summary-bias-econ", label: "Summary Bias", sub: "Economics" }} selected={selected} onSelect={setSelected} />
            <NavItem item={{ id: "exp-summary-bias-phys", label: "Summary Bias", sub: "Comp Physics" }} selected={selected} onSelect={setSelected} />
          </CollapsibleGroup>
        </nav>

        <div className="flex-1 min-w-0">
          {meta.title && (
            <div className="mb-4 pb-3 border-b border-border">
              <h2 className="font-heading text-lg font-semibold" data-testid="section-title">{meta.title}</h2>
              {meta.desc && <p className="text-xs text-muted-foreground mt-0.5">{meta.desc}</p>}
            </div>
          )}

          {selected === "pw-qeios" && <QeiosPairwiseSection />}
          {selected === "pw-scipost" && <SciPostPairwiseSection />}
          {selected.startsWith("pw-h2h-") && (() => {
            const ds = pairwiseDatasets.find(d => `pw-h2h-${d.dataset_id}` === selected);
            return ds ? <PairwiseAgreementSection key={ds.dataset_id} datasetId={ds.dataset_id} datasetName={ds.name} /> : null;
          })()}
          {selected === "si-scipost" && <SciPostPage embedded />}
          {selected === "exp-summary-bias" && <SummaryBiasSection category="q-bio.BM" />}
          {selected === "exp-summary-bias-econ" && <SummaryBiasSection category="econ.GN" />}
          {selected === "exp-summary-bias-phys" && <SummaryBiasSection category="physics.comp-ph" />}
          {activeDataset && <DatasetView ds={activeDataset} isAdmin={isAdmin} hideHeader />}
        </div>
      </div>
    </div>
  );
}
