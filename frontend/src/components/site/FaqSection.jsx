import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

const FAQS = [
  { q: "What does Kurate rank?", a: "Kurate ranks scientific preprints and papers available through the platform's live data sources, organised by research category and ranking signals." },
  { q: "How are papers ranked?", a: "Kurate uses AI-assisted comparison, category-based leaderboards, and research intelligence signals to help identify papers that may deserve closer attention." },
  { q: "Are Kurate rankings the same as peer review?", a: "No. Kurate rankings are discovery signals. They do not replace peer review, expert judgement, or careful reading of the paper." },
  { q: "Can I browse rankings by category?", a: "Yes. Kurate supports category-based leaderboards so users can explore papers within specific research areas." },
  { q: "Can I filter by year or time period?", a: "Yes, where supported by the live data. The Paper Rankings panel exposes available year and time-period filters directly." },
  { q: "What do model agreement and validation signals mean?", a: "They provide additional context about ranking consistency and reliability where those signals are available." },
  { q: "Who is Kurate for?", a: "Kurate is designed for researchers, research teams, laboratories, institutions, postgraduate students, research supervisors, and readers who need to track fast-moving scientific work." },
  { q: "Does Kurate cover all scientific fields?", a: "Kurate covers the categories currently supported by its live data. The Browse Categories section reflects the active coverage." },
  { q: "Is Kurate only for arXiv papers?", a: "Kurate currently focuses on preprints distributed through arXiv-compatible data sources. Additional sources may be added over time." },
  { q: "Why use rankings instead of search alone?", a: "Search is useful when users know what they are looking for. Rankings help users discover papers they may not have searched for directly." },
  { q: "How should I interpret a high score?", a: "A high score should be treated as a signal that a paper may deserve closer reading within its category. It is not a guarantee of correctness or long-term impact." },
  { q: "Can I use Kurate for literature reviews?", a: "Kurate can support early-stage literature scanning and paper discovery, but formal literature reviews should still use systematic academic methods and expert judgement." },
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
