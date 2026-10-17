import type { InteractionMode } from "../api";
import { useLang } from "../hooks";
import Segmented from "./Segmented";

export type { InteractionMode };

interface Props {
  mode: InteractionMode;
  onChange: (mode: InteractionMode) => void;
  disabled?: boolean;
}

export default function InteractionModeSelector({ mode, onChange, disabled }: Props) {
  const { t } = useLang();
  return (
    <Segmented
      label={t("toolbar.interaction")}
      value={mode}
      onChange={onChange}
      disabled={disabled}
      options={[
        { value: "ask", label: t("interaction.ask"), icon: "message", title: t("interaction.askDesc") },
        { value: "confirm", label: t("interaction.confirm"), icon: "pause", title: t("interaction.confirmDesc") },
        { value: "auto", label: t("interaction.auto"), icon: "zap", title: t("interaction.autoDesc") },
      ]}
    />
  );
}
