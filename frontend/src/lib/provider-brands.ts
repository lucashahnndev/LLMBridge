export type ProviderBrand = {
  src: string;
  label: string;
};

const PROVIDER_BRANDS: Record<string, ProviderBrand> = {
  google: {
    src: '/providers/google-gemini.svg',
    label: 'Google Gemini'
  },
  openai: {
    src: '/providers/openai.svg',
    label: 'OpenAI'
  },
  github: {
    src: '/providers/github.svg',
    label: 'GitHub'
  },
  openrouter: {
    src: '/providers/openrouter.svg',
    label: 'OpenRouter'
  },
  anthropic: {
    src: '/providers/anthropic.svg',
    label: 'Anthropic'
  }
};

export function getProviderBrand(provider: string | null | undefined): ProviderBrand | null {
  if (!provider) {
    return null;
  }
  return PROVIDER_BRANDS[provider.trim().toLowerCase()] ?? null;
}
