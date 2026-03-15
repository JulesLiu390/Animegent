export type Lang = "zh" | "en";

const translations: Record<string, Record<Lang, string>> = {
  // ========== Common ==========
  "common.cancel": { zh: "取消", en: "Cancel" },
  "common.confirm": { zh: "确定", en: "Confirm" },
  "common.send": { zh: "发送", en: "Send" },
  "common.delete": { zh: "删除", en: "Delete" },
  "common.save": { zh: "保存", en: "Save" },
  "common.saving": { zh: "保存中...", en: "Saving..." },
  "common.copy": { zh: "复制", en: "Copy" },
  "common.edit": { zh: "编辑", en: "Edit" },
  "common.retry": { zh: "重试", en: "Retry" },
  "common.skip": { zh: "跳过", en: "Skip" },
  "common.refresh": { zh: "刷新", en: "Refresh" },
  "common.add": { zh: "添加", en: "Add" },
  "common.error": { zh: "错误", en: "Error" },
  "common.revert": { zh: "撤销", en: "Revert" },

  // ========== App / Layout ==========
  "app.selectProject": { zh: "请选择或新建一个项目", en: "Select or create a project" },

  // ========== Welcome Page ==========
  "welcome.title": { zh: "开始创作", en: "Start Creating" },
  "welcome.subtitle": { zh: "选择一个项目，或从最近的作品中继续", en: "Pick a project, or continue from your recent works" },
  "welcome.recentWorks": { zh: "最近作品", en: "Recent Works" },
  "welcome.empty": { zh: "还没有作品，选择一个项目开始吧", en: "No works yet — select a project to get started" },

  // ========== Project Selector ==========
  "project.label": { zh: "项目:", en: "Project:" },
  "project.select": { zh: "选择项目", en: "Select project" },
  "project.deleteConfirm": { zh: "确定删除项目 \"{name}\" 吗？所有素材将被删除。", en: "Delete project \"{name}\"? All assets will be removed." },
  "project.deleteTitle": { zh: "删除项目", en: "Delete project" },
  "project.namePlaceholder": { zh: "项目名称", en: "Project name" },
  "project.createNew": { zh: "+ 新建", en: "+ New" },
  "project.rename": { zh: "改名", en: "Rename" },
  "project.recent": { zh: "最近", en: "Recent" },
  "project.all": { zh: "全部", en: "All" },

  // ========== Chat Panel ==========
  "chat.appName": { zh: "Animegent", en: "Animegent" },
  "chat.appSubtitle": { zh: "动画条漫生成助手", en: "Anime Comic Strip Generator" },
  "chat.exampleHint": { zh: "试试: \"帮我检测这张图中的人脸\" 或 \"生成一个穿红裙子的女孩角色\"", en: "Try: \"Detect faces in this image\" or \"Generate a girl character in a red dress\"" },
  "chat.uploadHint": { zh: "可以上传图片或点击侧边栏素材引用到对话中", en: "Upload images or click sidebar assets to reference in chat" },
  "chat.inputPlaceholder": { zh: "输入消息，粘贴或拖拽图片... (Enter 发送)", en: "Type a message, paste or drop images... (Enter to send)" },
  "chat.uploadImage": { zh: "上传图片", en: "Upload image" },
  "chat.stop": { zh: "停止", en: "Stop" },
  "chat.dropHint": { zh: "松开以添加图片", en: "Drop to add images" },
  "chat.imageLabel": { zh: "(图片)", en: "(image)" },
  "chat.errorPrefix": { zh: "错误", en: "Error" },

  // ========== Task Plan ==========
  "plan.title": { zh: "任务计划", en: "Task Plan" },
  "plan.proposalTitle": { zh: "任务计划 — 请确认或调整：", en: "Task Plan — Confirm or adjust:" },
  "plan.needsConfirm": { zh: "需确认", en: "Confirm" },
  "plan.execute": { zh: "开始执行", en: "Execute" },
  "plan.autoExecute": { zh: "自动执行", en: "Auto" },
  "plan.steps": { zh: "步", en: "steps" },
  "plan.modifyPlan": { zh: "修改计划", en: "Modify" },
  "plan.revisePlaceholder": { zh: "输入修改指令，例如：不需要写剧本，直接生成...", en: "Enter revision, e.g.: skip the script, generate directly..." },
  "plan.nextStep": { zh: "下一步：", en: "Next: " },
  "plan.continue": { zh: "继续执行", en: "Continue" },
  "plan.sendAndContinue": { zh: "发送并继续", en: "Send & Continue" },
  "plan.addInstruction": { zh: "补充指令", en: "Instruct" },
  "plan.instructionPlaceholder": { zh: "输入补充指令...", en: "Enter additional instructions..." },

  // ========== Face Select ==========
  "face.detected": { zh: "检测到 {count} 张人脸，请选择要风格化的人脸：", en: "{count} faces detected. Select faces to stylize:" },
  "face.filtered": { zh: "已过滤：", en: "Filtered: " },
  "face.tooSmall": { zh: "{count} 张太小", en: "{count} too small" },
  "face.tooBlurry": { zh: "{count} 张模糊", en: "{count} too blurry" },
  "face.male": { zh: "男", en: "M" },
  "face.female": { zh: "女", en: "F" },
  "face.age": { zh: "{age}岁", en: "Age {age}" },
  "face.selectAll": { zh: "全选", en: "Select all" },
  "face.deselectAll": { zh: "取消全选", en: "Deselect all" },
  "face.stylizeSelected": { zh: "风格化选中", en: "Stylize selected" },
  "face.confirmedCount": { zh: "已确认风格化 {count} 张人脸", en: "Confirmed {count} faces for stylization" },
  "face.skipped": { zh: "已跳过风格化", en: "Stylization skipped" },

  // ========== Character Select ==========
  "char.confirmed": { zh: "已确认 {count} 个角色", en: "{count} characters confirmed" },
  "char.variants": { zh: "{count} 个造型", en: "{count} variants" },
  "char.characters": { zh: "角色素材", en: "Characters" },
  "char.faces": { zh: "人脸素材", en: "Faces" },
  "char.noMore": { zh: "没有更多素材", en: "No more assets" },
  "char.instruction": { zh: "请确认要使用的角色（点击角色可替换）：", en: "Confirm characters to use (click to replace):" },
  "char.categoryChar": { zh: "角色", en: "Character" },
  "char.categoryFace": { zh: "人脸", en: "Face" },
  "char.confirmSelection": { zh: "确认选择", en: "Confirm selection" },

  // ========== Tool Call ==========
  "tool.accept": { zh: "接受", en: "Accept" },
  "tool.reject": { zh: "拒绝", en: "Reject" },
  "tool.revise": { zh: "修改", en: "Revise" },
  "tool.revisePlaceholder": { zh: "输入修改指令...", en: "Enter revision instructions..." },
  "tool.accepted": { zh: "已接受", en: "Accepted" },
  "tool.rejected": { zh: "已拒绝", en: "Rejected" },

  // ========== Asset Sidebar ==========
  "sidebar.title": { zh: "素材库", en: "Assets" },
  "sidebar.empty": { zh: "暂无", en: "None" },
  "sidebar.deleteConfirm": { zh: "确定删除 \"{name}\" 吗？", en: "Delete \"{name}\"?" },

  // ========== Preview Panel ==========
  "preview.title": { zh: "预览", en: "Preview" },
  "preview.filename": { zh: "文件名", en: "Filename" },
  "preview.category": { zh: "分类", en: "Category" },
  "preview.description": { zh: "描述", en: "Description" },
  "preview.sourceFace": { zh: "来源人脸", en: "Source face" },
  "preview.sendToChat": { zh: "发送到聊天", en: "Send to chat" },
  "preview.edit": { zh: "编辑", en: "Edit" },
  "preview.preview": { zh: "预览", en: "Preview" },

  // ========== Conversation History ==========
  "history.title": { zh: "对话记录", en: "Sessions" },
  "history.search": { zh: "搜索对话...", en: "Search sessions..." },
  "history.newChat": { zh: "新对话", en: "New Chat" },
  "history.noHistory": { zh: "暂无对话记录", en: "No sessions yet" },
  "history.untitled": { zh: "新对话", en: "New Chat" },
  "history.delete": { zh: "删除", en: "Delete" },
  "history.deleteConfirm": { zh: "确定删除这条对话记录？", en: "Delete this conversation?" },
  "history.messages": { zh: "{count} 条消息", en: "{count} messages" },
  "history.today": { zh: "今天", en: "Today" },
  "history.yesterday": { zh: "昨天", en: "Yesterday" },
  "history.thisWeek": { zh: "本周", en: "This Week" },
  "history.thisMonth": { zh: "本月", en: "This Month" },
  "history.older": { zh: "更早", en: "Older" },

  // ========== Mode Selector ==========
  "mode.comic": { zh: "条漫", en: "Comic" },
  "mode.storyboard": { zh: "分镜", en: "Storyboard" },

  // ========== Interaction Mode ==========
  "interaction.ask": { zh: "Ask", en: "Ask" },
  "interaction.edit": { zh: "Edit", en: "Edit" },
  "interaction.plan": { zh: "Plan", en: "Plan" },

  // ========== Asset Categories ==========
  "cat.style": { zh: "风格设定", en: "Style" },
  "cat.input": { zh: "原始图片", en: "Originals" },
  "cat.stylized": { zh: "角色", en: "Characters" },
  "cat.faces": { zh: "人脸", en: "Faces" },
  "cat.scenes_stylized": { zh: "场景", en: "Scenes" },
  "cat.scenes_no_people": { zh: "场景(原图)", en: "Scenes (orig)" },
  "cat.panels": { zh: "条漫", en: "Panels" },
  "cat.scripts": { zh: "剧本", en: "Scripts" },
  "cat.clips": { zh: "视频片段", en: "Clips" },
  "cat.final_videos": { zh: "成片", en: "Final Videos" },
  "cat.storyboard_strips": { zh: "分镜条漫", en: "Storyboard Strips" },
  "cat.storyboard_frames": { zh: "分镜首帧", en: "Storyboard Frames" },
  "cat.storyboards": { zh: "分镜脚本", en: "Storyboards" },
  "cat.clip_scripts": { zh: "视频脚本", en: "Clip Scripts" },
};

export function t(key: string, lang: Lang, params?: Record<string, string | number>): string {
  const entry = translations[key];
  let text = entry?.[lang] ?? entry?.["zh"] ?? key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replace(`{${k}}`, String(v));
    }
  }
  return text;
}
