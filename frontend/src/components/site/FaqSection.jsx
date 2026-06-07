import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

const FAQS = [
  { q: "What does Kurate rank?", a: "Kurate ranks scientific preprints from supported arXiv categories, organised into category-based leaderboards." },
  { q: "How are papers ranked?", a: "Papers are evaluated through AI-assisted pairwise comparison within each arXiv category. Those comparisons produce a tournament-based Score. A separate process assigns each paper a standalone Rating on a 1.0-10.0 scale. Gap reports the percentile difference between Score and Rating." },
  { q: "Are Kurate rankings the same as peer review?", a: "No. Kurate rankings are discovery signals. They do not replace peer review, expert judgement, or careful reading of the paper." },
  { q: "Can I browse rankings by category?", a: "Yes. Kurate supports arXiv category-based leaderboards so users can explore papers within specific research areas." },
  { q: "Can I filter by time period?", a: "Yes. The Paper Rankings panel exposes time-period filters such as Newly Added, Last 7 Days, Last 30 Days, and All Time." },
  { q: "What do Score, Rating, and Gap mean?", a: "Score is the comparative tournament-based ranking score derived from AI-assisted pairwise comparisons within a category. Rating is a standalone scientific impact rating on a 1.0-10.0 scale and is not based on pairwise comparison. Gap is the percentile difference between the comparative Score and the standalone Rating — it shows how far the two signals diverge for a given paper." },
  { q: "Is Kurate based on arXiv?", a: "Kurate currently focuses on preprints distributed through arXiv-compatible data sources." },
  { q: "Can Kurate help with literature discovery?", a: "Kurate can support early-stage literature scanning and paper discovery, but formal literature reviews should still use systematic academic methods and expert judgement." },
  { q: "How often are rankings updated?", a: "Rankings are updated continuously as new papers are processed by the platform. The Paper Rankings panel reflects the latest update timestamp." },
];

export function FaqSection() {
  return (
    <section id="faq" className="w-full border-t border-slate-200 bg-slate-50/40" data-testid="faq-section">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Frequently Asked Questions</span>
        <h2 className="font-serif text-2xl sm:text-3xl text-slate-900 mt-1">Methodology, scope, and how to interpret Kurate signals.</h2>
        <p className="text-sm text-slate-500 max-w-xl mt-2">
          Practical answers about what the platform does, how rankings are produced, and how they should be used in research workflows.
        </p>

        <Accordion type="single" collapsible className="mt-8 max-w-2xl">
          {FAQS.map((f, i) => (
            <AccordionItem key={i} value={`faq-${i}`} className="border-slate-200">
              <AccordionTrigger className="text-sm text-left text-slate-900 hover:no-underline py-4" data-testid={`faq-trigger-${i}`}>
                {f.q}
              </AccordionTrigger>
              <AccordionContent className="text-sm text-slate-600 leading-relaxed pb-4">
                {f.a}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </div>
    </section>
  );
}
