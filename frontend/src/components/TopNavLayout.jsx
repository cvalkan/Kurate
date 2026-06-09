import TopNav from "@/components/site/TopNav";

/** Wraps any existing page with the new TopNav + kurate-homepage font scope */
export default function TopNavLayout({ children }) {
  return (
    <div className="kurate-homepage">
      <TopNav />
      {children}
    </div>
  );
}
