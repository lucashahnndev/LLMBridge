import { writable } from 'svelte/store';

export type SectionKey = 'overview' | 'keys' | 'tokens' | 'queues' | 'usage' | 'runtime';

export const activeSection = writable<SectionKey>('overview');
export const topbarTitle = writable<string>('Overview');
export const refreshTrigger = writable<number>(0);
export const sidebarCollapsed = writable<boolean>(false);
