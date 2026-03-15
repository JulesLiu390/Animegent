import { useState, useEffect } from "react";
import type { ShowcaseItem } from "../api";
import { fetchShowcase, getFileUrl } from "../api";
import { useLang } from "../LanguageContext";

interface Props {
  onSelectProject: (name: string) => void;
}

export default function WelcomePage({ onSelectProject }: Props) {
  const { t } = useLang();
  const [items, setItems] = useState<ShowcaseItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchShowcase()
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Hero */}
      <div className="flex flex-col items-center pt-16 pb-10 px-6">
        <img src="/logo.png" alt="Animegent" className="w-16 h-16 rounded-2xl mb-4" />
        <h1 className="text-3xl font-bold text-gray-800 dark:text-gray-100 mb-2 tracking-tight">
          {t("welcome.title")}
        </h1>
        <p className="text-sm text-gray-400 dark:text-gray-500">
          {t("welcome.subtitle")}
        </p>
      </div>

      {/* Gallery */}
      {loading ? (
        <div className="flex justify-center py-12">
          <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : items.length > 0 ? (
        <div className="px-8 pb-12">
          <div className="text-[11px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-4 text-center">
            {t("welcome.recentWorks")}
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 max-w-3xl mx-auto">
            {items.map((item, i) => (
              <button
                key={`${item.project}-${item.name}-${i}`}
                onClick={() => onSelectProject(item.project)}
                className="group text-left"
              >
                <div className="relative aspect-video rounded-xl overflow-hidden border border-gray-200/80 dark:border-gray-700/80 group-hover:border-blue-400 dark:group-hover:border-blue-500 shadow-sm group-hover:shadow-md transition-all">
                  <img
                    src={getFileUrl(item.url)}
                    alt={item.name}
                    className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300"
                  />
                </div>
                <div className="mt-1.5 px-0.5">
                  <div className="text-xs font-medium text-gray-600 dark:text-gray-300 truncate">
                    {item.project}
                  </div>
                  <div className="text-[10px] text-gray-400 dark:text-gray-500 truncate">
                    {item.name}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center py-12 text-gray-300 dark:text-gray-600">
          <svg className="w-12 h-12 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
          </svg>
          <p className="text-xs">{t("welcome.empty")}</p>
        </div>
      )}
    </div>
  );
}
