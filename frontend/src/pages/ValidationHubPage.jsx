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
import DeeperDiveSection from "./DeeperDiveSection";
import ICLRDeepDiveSection from "./ICLRDeepDiveSection";
import ExtendedThinkingSection from "./ExtendedThinkingSection";
import TieExperimentSection from "./TieExperimentSection";
import MultiAspectSection from "./MultiAspectSection";
import SummarizerABSection from "./SummarizerABSection";
import AssessorEvaluatorSection from "./AssessorEvaluatorSection";
import JudgeComparisonSection from "./JudgeComparisonSection";
import ModelCorrelationSection from "./ModelCorrelationSection";
import CycleAnalysisSection from "./CycleAnalysisSection";
import SamePairsSection from "./SamePairsSection";
import InstitutionBiasSection from "./InstitutionBiasSection";
import AllPairsSection from "./AllPairsSection";
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
  const [selected, setSelected] = useState(null);
  const [datasets, setDatasets] = useState([]);
  const isAdmin = !!sessionStorage.getItem("admin_token");

  const fetchDatasets = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/validation/datasets`);
      const ds = r.data.datasets || [];
      setDatasets(ds);
      // Auto-select first available item
      if (!selected && ds.length) {
        if (isAdmin) {
          setSelected("pw-qeios");
        } else {
          // Public: default to first ICLR tournament dataset
          const iclr = ds.find(d => d.name?.startsWith("ICLR "));
          if (iclr) setSelected(`t-${iclr.dataset_id}`);
          else setSelected(`t-${ds[0].dataset_id}`);
        }
      }
    } catch (e) { console.error(e); }
  }, [isAdmin]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchDatasets(); }, [fetchDatasets]);

  const pairwiseDatasets = datasets;
  const allTournamentGroups = groupDatasets(datasets);
  const pairwiseGroups = groupDatasets(datasets);

  // Public users only see ICLR, eLife, MIDL tournaments
  const PUBLIC_SOURCES = new Set(["ICLR", "eLife", "MIDL"]);
  const tournamentGroups = isAdmin
    ? allTournamentGroups
    : Object.fromEntries(Object.entries(allTournamentGroups).filter(([source]) => PUBLIC_SOURCES.has(source)));

  // Auto-open the group containing the selected item
  const selectedTournamentSource = Object.entries(tournamentGroups).find(
    ([, items]) => items.some(ds => `t-${ds.dataset_id}` === selected)
  )?.[0];
  const selectedPairwiseSource = Object.entries(pairwiseGroups).find(
    ([, items]) => items.some(ds => `pw-h2h-${ds.dataset_id}` === selected)
  )?.[0];

  const activeDataset = datasets.find(ds => selected === `t-${ds.dataset_id}`);

  const sectionMeta = {
    "pw-qeios": { title: "Pairwise — Qeios (Legacy)", desc: "Head-to-head AI comparison using Qeios open peer review data. Separate dataset — not part of main validation system." },
    "pw-scipost": { title: "Pairwise — SciPost (Legacy)", desc: "Per-dimension head-to-head comparison using SciPost peer review data. Separate dataset — not part of main validation system." },
    "si-scipost": { title: "Single-item — SciPost (Legacy)", desc: "AI rates each paper on 4 dimensions (1-6 scale). Separate dataset." },
    "exp-summarizer-ab": { title: "Opus 4.5 vs 4.6", desc: "Which summarizer helps AI judges agree with human experts more? Pairwise comparison across ICLR and eLife datasets." },
    "exp-summary-bias": { title: "Summary Bias — Biomolecules", desc: "Does the LLM that wrote the summary bias the judge? 3 judges x 3 summary sources x 200 matches." },
    "exp-summary-bias-econ": { title: "Summary Bias — Economics", desc: "Does the LLM that wrote the summary bias the judge? 3 judges x 3 summary sources x 200 matches." },
    "exp-summary-bias-phys": { title: "Summary Bias — Comp Physics", desc: "Does the LLM that wrote the summary bias the judge? 3 judges x 3 summary sources x 200 matches." },
    "exp-thinking-overview": { title: "Extended Thinking", desc: "Does giving the summarizer a thinking budget improve agreement with human experts? Compares Opus 4.6 standard vs Opus 4.6 with extended thinking." },
    "exp-tie-allowed": { title: "Tie-Allowed Judging", desc: "Does allowing AI judges to declare ties improve accuracy on decisive pairs? Compares forced-choice vs tie-allowed prompts on the same opus46 pairs." },
    "exp-multi-aspect": { title: "Multi-Aspect Judging", desc: "Does breaking the judgment into 5 separate dimensions (novelty, applications, rigor, breadth, timeliness) improve accuracy over a single holistic verdict?" },
    "exp-judge-comparison": { title: "Accuracy by Judge", desc: "Which LLM is the best judge? Head-to-head comparison of accuracy, ranking correlation, and ensemble methods on identical pairs (4 judges × 9 datasets × 200 pairs)." },
    "exp-summarizer-cross": { title: "Accuracy by Summarizer", desc: "How does the choice of summarizer model (GPT-5.2, Gemini 3 Pro, Opus 4.5/4.6) affect tournament accuracy? Same-pair comparison across 12 ICLR and eLife datasets." },
    "exp-assessor-evaluator": { title: "Summarizer × Judge Matrix", desc: "Full interaction matrix: which model should write the summary vs. judge the comparison? 5 summarizers × 4 judge strategies on identical pairs." },
    "exp-consistency": { title: "Verdict Stability", desc: "Controlled comparison: how often does the same pair get a different verdict under different models or formats?" },
    "exp-cycle-analysis": { title: "Intransitive Cycles", desc: "Condorcet paradox analysis: how often does A>B, B>C, but C>A? By model, format, and dataset." },
    "exp-model-correlation": { title: "Model Correlation", desc: "How much do different judge models agree on the same pairs? Pairwise agreement by dataset and input format." },
    "exp-institution-bias": { title: "Institution Bias", desc: "Do AI judges favor papers from prestigious institutions (Google, Stanford, MIT) more than human reviewers? Analysis across 12 datasets using author affiliation extraction." },
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
        <div className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-amber-50 border border-amber-200 text-amber-800 text-xs font-medium">
          <FlaskConical className="h-3 w-3" />
          Work in progress — results are preliminary and actively being refined
        </div>
      </div>

      <div className="flex gap-5">
        <nav className="w-56 shrink-0 space-y-3 max-h-[calc(100vh-120px)] overflow-y-auto" data-testid="validation-sidebar">
          {/* Pairwise — admin only */}
          {isAdmin && (
            <CollapsibleGroup label="Pairwise" icon={GitCompare} defaultOpen={selected?.startsWith("pw-")}>
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
              <CollapsibleGroup label="Legacy" defaultOpen={selected === "pw-qeios" || selected === "pw-scipost"}>
                <NavItem item={{ id: "pw-qeios", label: "Qeios", sub: "Separate dataset" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "pw-scipost", label: "SciPost", sub: "Separate dataset" }} selected={selected} onSelect={setSelected} />
              </CollapsibleGroup>
            </CollapsibleGroup>
          )}

          {/* Single-item — admin only */}
          {isAdmin && (
            <CollapsibleGroup label="Single-item (Legacy)" icon={Beaker} defaultOpen={selected === "si-scipost"}>
              <NavItem item={{ id: "si-scipost", label: "SciPost" }} selected={selected} onSelect={setSelected} />
            </CollapsibleGroup>
          )}

          {/* Tournament — public shows ICLR/eLife/MIDL only */}
          <CollapsibleGroup label="Tournament" icon={Trophy} defaultOpen={!selected || selected?.startsWith("t-")}>
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

          {/* Experiments — admin only */}
          {isAdmin && (
            <CollapsibleGroup label="Experiments" icon={FlaskRound} defaultOpen={selected?.startsWith("exp-")}>
              <CollapsibleGroup label="Summarizer Quality" defaultOpen={selected === "exp-summarizer-cross" || selected === "exp-summarizer-ab" || selected === "exp-thinking-overview"}>
                <NavItem item={{ id: "exp-summarizer-cross", label: "Accuracy by Summarizer", sub: "GPT vs Gemini vs Opus" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-summarizer-ab", label: "Opus 4.5 vs 4.6", sub: "A/B test" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-thinking-overview", label: "Extended Thinking", sub: "Thinking budget effect" }} selected={selected} onSelect={setSelected} />
              </CollapsibleGroup>
              <CollapsibleGroup label="Judge Quality" defaultOpen={selected === "exp-judge-comparison" || selected === "exp-assessor-evaluator"}>
                <NavItem item={{ id: "exp-judge-comparison", label: "Accuracy by Judge", sub: "Single judge vs round-robin" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-assessor-evaluator", label: "Summarizer × Judge Matrix", sub: "Full interaction" }} selected={selected} onSelect={setSelected} />
              </CollapsibleGroup>
              <CollapsibleGroup label="Consistency & Reliability" defaultOpen={selected === "exp-cycle-analysis" || selected === "exp-consistency" || selected === "exp-model-correlation"}>
                <NavItem item={{ id: "exp-consistency", label: "Verdict Stability", sub: "Same-pair flips across conditions" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-cycle-analysis", label: "Intransitive Cycles", sub: "Condorcet paradox by context" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-model-correlation", label: "Model Correlation", sub: "Pairwise agreement matrices" }} selected={selected} onSelect={setSelected} />
              </CollapsibleGroup>
              <CollapsibleGroup label="Prompt Variants" defaultOpen={selected === "exp-tie-allowed" || selected === "exp-multi-aspect"}>
                <NavItem item={{ id: "exp-tie-allowed", label: "Tie-Allowed", sub: "Allow AI to abstain" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-multi-aspect", label: "Multi-Aspect", sub: "5-dimension judgments" }} selected={selected} onSelect={setSelected} />
              </CollapsibleGroup>
              <CollapsibleGroup label="Second Pass (Deep Dive)" defaultOpen={selected?.includes("deep-dive") || selected === "exp-deeper-dive"}>
                <NavItem item={{ id: "exp-deeper-dive", label: "Meta-evaluation", sub: "Overview" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-iclr-deep-dive", label: "Code Generation", sub: "ICLR" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-fairness-deep-dive", label: "Fairness", sub: "ICLR" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-molecules-deep-dive", label: "Molecules", sub: "ICLR" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-pdes-deep-dive", label: "PDEs & Dyn. Systems", sub: "ICLR" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-midl-deep-dive", label: "Medical Imaging", sub: "MIDL" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-neuro-deep-dive", label: "Neuroscience", sub: "eLife" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-peerread-deep-dive", label: "ACL 2017", sub: "PeerRead" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-acmi-deep-dive", label: "Microbiology 100", sub: "ACMI" }} selected={selected} onSelect={setSelected} />
              </CollapsibleGroup>
              <CollapsibleGroup label="Summary Bias" defaultOpen={selected?.startsWith("exp-summary-bias") || selected === "exp-institution-bias"}>
                <NavItem item={{ id: "exp-institution-bias", label: "Institution Bias", sub: "Prestige analysis" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-summary-bias", label: "Biomolecules", sub: "3 judges × 3 sources" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-summary-bias-econ", label: "Economics", sub: "3 judges × 3 sources" }} selected={selected} onSelect={setSelected} />
                <NavItem item={{ id: "exp-summary-bias-phys", label: "Comp Physics", sub: "3 judges × 3 sources" }} selected={selected} onSelect={setSelected} />
              </CollapsibleGroup>
            </CollapsibleGroup>
          )}
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
          {selected?.startsWith("pw-h2h-") && (() => {
            const ds = pairwiseDatasets.find(d => `pw-h2h-${d.dataset_id}` === selected);
            return ds ? <PairwiseAgreementSection key={ds.dataset_id} datasetId={ds.dataset_id} datasetName={ds.name} /> : null;
          })()}
          {selected === "si-scipost" && <SciPostPage embedded />}
          {selected === "exp-summarizer-ab" && <SummarizerComparisonSection />}
          {selected === "exp-summary-bias" && <SummaryBiasSection category="q-bio.BM" />}
          {selected === "exp-summary-bias-econ" && <SummaryBiasSection category="econ.GN" />}
          {selected === "exp-summary-bias-phys" && <SummaryBiasSection category="physics.comp-ph" />}
          {selected === "exp-deeper-dive" && <DeeperDiveSection />}
          {selected === "exp-iclr-deep-dive" && <ICLRDeepDiveSection datasetId="iclr-codegen" label="ICLR Code Generation" />}
          {selected === "exp-midl-deep-dive" && <ICLRDeepDiveSection datasetId="midl-medical-imaging" label="MIDL Medical Imaging" />}
          {selected === "exp-pdes-deep-dive" && <ICLRDeepDiveSection datasetId="iclr-pdes" label="ICLR PDEs & Dynamical Systems" />}
          {selected === "exp-neuro-deep-dive" && <ICLRDeepDiveSection datasetId="elife-neuro-100" label="eLife Neuroscience" />}
          {selected === "exp-peerread-deep-dive" && <ICLRDeepDiveSection datasetId="peerread_acl_2017" label="PeerRead ACL 2017" />}
          {selected === "exp-acmi-deep-dive" && <ICLRDeepDiveSection datasetId="acmi-micro-100" label="Access Microbiology (100 papers)" />}
          {selected === "exp-fairness-deep-dive" && <ICLRDeepDiveSection datasetId="iclr-fairness" label="ICLR Fairness" />}
          {selected === "exp-molecules-deep-dive" && <ICLRDeepDiveSection datasetId="iclr-molecules" label="ICLR Molecules" />}
          {selected === "exp-thinking-overview" && <ExtendedThinkingSection />}
          {selected === "exp-tie-allowed" && <TieExperimentSection />}
          {selected === "exp-multi-aspect" && <MultiAspectSection />}
          {selected === "exp-summarizer-cross" && <SummarizerABSection />}
          {selected === "exp-assessor-evaluator" && <AssessorEvaluatorSection />}
          {selected === "exp-judge-comparison" && <JudgeComparisonSection />}
          {selected === "exp-cycle-analysis" && <AllPairsSection />}
          {selected === "exp-consistency" && <SamePairsSection />}
          {selected === "exp-model-correlation" && <ModelCorrelationSection />}
          {selected === "exp-institution-bias" && <InstitutionBiasSection />}
          {activeDataset && <DatasetView ds={activeDataset} isAdmin={isAdmin} hideHeader />}
        </div>
      </div>
    </div>
  );
}
