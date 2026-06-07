import TopNav from "@/components/site/TopNav";
import HeroPanel from "@/components/site/HeroPanel";
import {
  RecentRankings, ResearchAndCapabilities, HowItWorks, WhyCategories,
  WhatMakesDifferent, WhoFor, TrustPanel,
} from "@/components/site/ContentSections";
import { FaqSection } from "@/components/site/FaqSection";
import SiteFooter from "@/components/site/SiteFooter";

export default function HomePage() {
  return (
    <>
      <TopNav />
      <HeroPanel />
      <RecentRankings />
      <ResearchAndCapabilities />
      <HowItWorks />
      <WhyCategories />
      <WhatMakesDifferent />
      <WhoFor />
      <TrustPanel />
      <FaqSection />
      <SiteFooter />
    </>
  );
}
