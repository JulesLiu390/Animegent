import type { CreationMode } from "../api";
import { useLang } from "../hooks";
import Segmented from "./Segmented";

interface Props {
  mode: CreationMode;
  onChange: (mode: CreationMode) => void;
  disabled?: boolean;
}

export default function ModeSelector({ mode, onChange, disabled }: Props) {
  const { t } = useLang();
  return (
    <Segmented
      label={t("toolbar.mode")}
      value={mode}
      onChange={onChange}
      disabled={disabled}
      options={[
        { value: "comic", label: t("mode.comic"), icon: "panels", title: t("mode.comicDesc") },
        { value: "storyboard", label: t("mode.storyboard"), icon: "film", title: t("mode.storyboardDesc") },
      ]}
    />
  );
}
