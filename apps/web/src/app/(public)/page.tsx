import Navbar from "@/components/layout/Navbar";
import Footer from "@/components/layout/Footer";
import Hero from "@/components/sections/Hero";
import HowItWorks from "@/components/sections/HowItWorks";
import TheCrisis from "@/components/sections/TheCrisis";
import TransformationPromise from "@/components/sections/TransformationPromise";
import ProductPreview from "@/components/sections/ProductPreview";
import Features from "@/components/sections/Features";
import Pricing from "@/components/sections/Pricing";
import FAQ from "@/components/sections/FAQ";
import JourneyToSelfReliance from "@/components/sections/JourneyToSelfReliance";
import FinalCTA from "@/components/sections/FinalCTA";

export default function Home() {
  return (
    <>
      <Navbar />
      <main className="flex-1">
        <Hero />
        <TheCrisis />
        <TransformationPromise />
        <Features />
        <HowItWorks />
        <ProductPreview />
        <JourneyToSelfReliance />
        <Pricing />
        <FAQ />
        <FinalCTA />
      </main>
      <Footer />
    </>
  );
}
