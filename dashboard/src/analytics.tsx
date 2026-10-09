import { useEffect } from 'react';

type EventData = Record<string, string | number | boolean>;

declare global {
  interface Window {
    umami?: { track(name: string, data?: EventData): void };
  }
}

const scriptUrl = import.meta.env.VITE_UMAMI_SCRIPT_URL?.trim();
const websiteId = import.meta.env.VITE_UMAMI_WEBSITE_ID?.trim();
const domains = import.meta.env.VITE_UMAMI_DOMAINS?.trim();

export function trackAnalyticsEvent(name: string, data?: EventData) {
  window.umami?.track(name, data);
}

export function Analytics() {
  useEffect(() => {
    if (!scriptUrl || !websiteId || document.querySelector('script[data-token-by-token-analytics]')) return;
    const script = document.createElement('script');
    script.defer = true;
    script.src = scriptUrl;
    script.dataset.websiteId = websiteId;
    script.dataset.doNotTrack = 'true';
    script.dataset.tokenByTokenAnalytics = 'umami';
    if (domains) script.dataset.domains = domains;
    document.head.append(script);
    return () => script.remove();
  }, []);
  return null;
}

export function useEngagementAnalytics(page: string, section: string) {
  useEffect(() => {
    if (section) trackAnalyticsEvent('section-view', { page, section });
  }, [page, section]);

  useEffect(() => {
    const recorded = new Set<number>();
    const update = () => {
      const available = document.documentElement.scrollHeight - innerHeight;
      const percent = available <= 0 ? 100 : Math.round(scrollY / available * 100);
      for (const threshold of [25, 50, 75, 100]) {
        if (percent >= threshold && !recorded.has(threshold)) {
          recorded.add(threshold);
          trackAnalyticsEvent('scroll-depth', { page, percent: threshold });
        }
      }
    };
    addEventListener('scroll', update, { passive: true });
    update();
    return () => removeEventListener('scroll', update);
  }, [page]);
}
