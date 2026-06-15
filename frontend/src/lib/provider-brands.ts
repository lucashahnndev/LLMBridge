export type ProviderBrand = {
  src: string;
  label: string;
};

const PROVIDER_BRANDS: Record<string, ProviderBrand> = {
  google: {
    src: '/providers/google.ico',
    label: 'Google'
  },
  openai: {
    src: '/providers/openai.svg',
    label: 'OpenAI'
  },
  github: {
    src: '/providers/github.ico',
    label: 'GitHub'
  },
  openrouter: {
    src: '/providers/openrouter.ico',
    label: 'OpenRouter'
  },
  anthropic: {
    src: '/providers/anthropic.png',
    label: 'Anthropic'
  }
};

export function getProviderBrand(provider: string | null | undefined): ProviderBrand | null {
  if (!provider) {
    return null;
  }
  return PROVIDER_BRANDS[provider.trim().toLowerCase()] ?? null;
}
