import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

const FAQS = [
  { q: "What does Kurate rank?", a: "Kurate ranks scientific preprints from supported arXiv categories, organised into category-based leaderboards." },
  { q: "How are papers ranked?", a: "Papers are evaluated through AI-assisted pairwise comparison. Comparison outputs are combined into category-based rankings with a Score, Rating, and Gap for each paper." },
  { q: "Are Kurate rankings the same as peer review?", a: "No. Kurate rankings are discovery signals. They do not replace peer review, expert judgement, or careful reading of the paper." },
  { q: "Can I browse rankings by category?", a: "Yes. Kurate supports arXiv category-based leaderboards so users can explore papers within specific research areas." },
  { q: "Can I filter by time period?", a: "Yes. The Paper Rankings panel exposes time-period filters such as Newly Added, Last 7 Days, Last 30 Days, and All Time." },
  { q: "What do Score, Rating, and Gap mean?", a: "Score reflects a paper's tournament performance from AI-assisted comparisons. Rating is a comparative value used to order papers. Gap measures the separation between adjacent papers in the leaderboard." },
  { q: "Is Kurate based on arXiv?", a: "Kurate currently focuses on preprints distributed through arXiv-compatible data sources." },
  { q: "Can Kurate help with literature discovery?", a: "Kurate can support early-stage literature scanning and paper discovery, but formal literature reviews should still use systematic academic methods and expert judgement." },
  { q: "How often are rankings updated?", a: "Rankings are updated continuously as new papers are processed by the platform. The Paper Rankings panel reflects the latest update timestamp." },
];

export function FaqSection() {
  return (
    <section className="bg-white border-t border-slate-200">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10">
          <div className="lg:col-span-4">
            <div className="text-xs font-medium uppercase tracking-[0.12em] text-blue-600 mb-2">Frequently Asked Questions</div>
            <h2 className="font-serif text-3xl sm:text-4xl font-medium text-slate-900 leading-tight">Methodology, scope, and how to interpret Kurate signals.</h2>
            <p className="mt-4 text-base text-slate-600 leading-relaxed">Practical answers about what the platform does, how rankings are produced, and how they should be used in research workflows.</p>
          </div>
          <div className="lg:col-span-8">
            <Accordion type="single" collapsible className="w-full border-t border-slate-200">
              {FAQS.map((f, i) => (
                <AccordionItem key={i} value={`item-${i}`} className="border-b border-slate-200">
                  <AccordionTrigger
                    data-testid={`faq-trigger-${i}`}
                    className="font-serif text-lg text-slate-900 font-medium hover:text-blue-600 hover:no-underline transition-colors text-left py-5"
                  >
                    {f.q}
                  </AccordionTrigger>
                  <AccordionContent data-testid={`faq-content-${i}`} className="text-base text-slate-600 leading-relaxed pb-5">
                    {f.a}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        </div>
      </div>
    </section>
  );
}
