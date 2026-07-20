'use client'

import { OnboardingFlow } from '@/components/onboarding/OnboardingFlow'

export default function OnboardingPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-neutral-50 px-4 py-12">
      <OnboardingFlow />
    </div>
  )
}
