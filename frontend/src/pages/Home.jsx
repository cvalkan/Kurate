import TopNav from "@/components/site/TopNav";
import HeroPanel from "@/components/site/HeroPanel";
import {
  RecentRankings, BrowseCategories, LatestActivity, ResearchSignals,
  HowItWorks, WhyCategories, PlatformCapabilities, WhatMakesDifferent,
  WhoFor, TrustPanel,
} from "@/components/site/ContentSections";
import { FaqSection } from "@/components/site/FaqSection";
import SiteFooter from "@/components/site/SiteFooter";

export default function Home() {
  return (
    <div className="min-h-screen bg-white" data-testid="home-page">
      <TopNav />
      <HeroPanel />
      <RecentRankings />
      <BrowseCategories />
      <LatestActivity />
      <ResearchSignals />
      <HowItWorks />
      <WhyCategories />
      <PlatformCapabilities />
      <WhatMakesDifferent />
      <WhoFor />
      <TrustPanel />
      <div id="faq">
        <FaqSection />
      </div>
      <SiteFooter />
    </div>
  );
}
