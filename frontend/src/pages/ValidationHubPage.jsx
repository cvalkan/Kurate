import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import {
  FlaskConical, GitCompare, Beaker, Trophy, ChevronRight,
} from "lucide-react";

import PairwisePage from "./PairwisePage";
import SciPostPage from "./SciPostPage";
import SciPostPairwiseSection from "./SciPostPairwiseSection";
import QeiosPairwiseSection from "./QeiosPairwiseSection";
import PairwiseAgreementSection from "./PairwiseAgreementSection";
import { DatasetView } from "./ValidationPage";

const API = process.env.REACT_APP_BACKEND_URL;

const STATIC_SECTIONS = [
  {
    group: "Pairwise",
    icon: GitCompare,
    description: "Head-to-head: AI picks which paper is better, compared with human verdict",
    items: [
      { id: "pw-qeios", label: "Qeios" },
      { id: "pw-scipost", label: "SciPost" },
    ],
    dynamicItems: true,
  },
  {
    group: "Single-item",
    icon: Beaker,
    description: "AI rates individual papers on specific dimensions, compared with human ratings",
    items: [
      { id: "si-scipost", label: "SciPost" },
    ],
  },
  {
    group: "Tournament",
    icon: Trophy,
    description: "Full ranking correlation: AI tournament ranking vs human peer-review ranking",
    items: [], // populated dynamically
  },
];

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

  // Datasets that have pairwise head-to-head data potential — all validation datasets
  const pairwiseDatasets = datasets;

  // Build sections with dynamic items
  const sections = STATIC_SECTIONS.map(s => {
    if (s.group === "Pairwise") {
      return {
        ...s,
        items: [
          ...s.items,
          ...pairwiseDatasets.map(ds => ({
            id: `pw-h2h-${ds.dataset_id}`,
            label: ds.name,
            datasetId: ds.dataset_id,
            sub: `${ds.papers} papers`,
          })),
        ],
      };
    }
    if (s.group === "Tournament") {
      return {
        ...s,
        items: datasets.map(ds => ({
          id: `t-${ds.dataset_id}`,
          label: ds.name,
          datasetId: ds.dataset_id,
          sub: `${ds.papers} papers`,
        })),
      };
    }
    return s;
  });

  // Find the active dataset for tournament views
  const activeDataset = datasets.find(ds => selected === `t-${ds.dataset_id}`);

  // Section descriptions for the content header
  const sectionMeta = {
    "pw-qeios": { title: "Pairwise — Qeios", desc: "Head-to-head AI comparison using Qeios open peer review data. 3 AI models, majority-vote agreement with human expert." },
    "pw-scipost": { title: "Pairwise — SciPost", desc: "Per-dimension head-to-head comparison (validity, significance, originality, clarity) using SciPost peer review data." },
    "si-scipost": { title: "Single-item — SciPost", desc: "AI rates each paper on 4 dimensions (1-6 scale), compared against human referee ratings." },
  };
  // Add H2H dataset metas
  pairwiseDatasets.forEach(ds => {
    sectionMeta[`pw-h2h-${ds.dataset_id}`] = {
      title: `Pairwise — ${ds.name}`,
      desc: `How often do different input formats (Abstract, Extract, Full PDF) and AI models agree with human expert judgments?`,
    };
  });
  if (activeDataset) {
    sectionMeta[selected] = { title: `Tournament — ${activeDataset.name}`, desc: activeDataset.description || activeDataset.source || "" };
  }
  const meta = sectionMeta[selected] || { title: "", desc: "" };

  return (
    <div className="container mx-auto px-4 md:px-6 max-w-7xl py-6 md:py-10">
      {/* Page header */}
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
        {/* Sidebar */}
        <nav className="w-52 shrink-0 space-y-4" data-testid="validation-sidebar">
          {sections.map(section => (
            <div key={section.group}>
              <div className="flex items-center gap-1.5 px-2 mb-1">
                <section.icon className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {section.group}
                </span>
              </div>
              <div className="space-y-0.5">
                {section.items.map(item => (
                  <button
                    key={item.id}
                    onClick={() => setSelected(item.id)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors flex items-center justify-between ${
                      selected === item.id
                        ? "bg-accent/10 text-accent font-medium border border-accent/20"
                        : "text-muted-foreground hover:bg-secondary/30 hover:text-foreground border border-transparent"
                    }`}
                    data-testid={`nav-${item.id}`}
                  >
                    <div>
                      <div className="text-xs font-medium">{item.label}</div>
                      {item.sub && <div className="text-[10px] opacity-60 mt-0.5">{item.sub}</div>}
                    </div>
                    {selected === item.id && <ChevronRight className="h-3 w-3 shrink-0" />}
                  </button>
                ))}
                {section.items.length === 0 && (
                  <div className="px-3 py-2 text-[10px] text-muted-foreground/50 italic">No datasets yet</div>
                )}
              </div>
            </div>
          ))}
        </nav>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {/* Section header */}
          {meta.title && (
            <div className="mb-4 pb-3 border-b border-border">
              <h2 className="font-heading text-lg font-semibold" data-testid="section-title">{meta.title}</h2>
              {meta.desc && <p className="text-xs text-muted-foreground mt-0.5">{meta.desc}</p>}
            </div>
          )}

          {/* Section content */}
          {selected === "pw-qeios" && <QeiosPairwiseSection />}
          {selected === "pw-scipost" && <SciPostPairwiseSection />}
          {selected.startsWith("pw-h2h-") && (() => {
            const ds = pairwiseDatasets.find(d => `pw-h2h-${d.dataset_id}` === selected);
            return ds ? <PairwiseAgreementSection key={ds.dataset_id} datasetId={ds.dataset_id} datasetName={ds.name} /> : null;
          })()}
          {selected === "si-scipost" && <SciPostPage embedded />}
          {activeDataset && <DatasetView ds={activeDataset} isAdmin={isAdmin} hideHeader />}
        </div>
      </div>
    </div>
  );
}
