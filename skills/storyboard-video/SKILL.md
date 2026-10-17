---
name: 分镜视频
description: 分镜模式下做动画视频的完整流程：剧情脚本、分镜脚本 JSON、生成首帧、每个片段的视频脚本、生成和合并视频。收到做分镜、做视频的请求时，先读它再开始。
version: 1.0.0
scopes: [storyboard]
---

# 分镜视频的工作流

收到请求后先简要说明步骤，再按顺序执行。

1. 先用 list_files 查看 output/stylized/ 目录，了解已有角色。
2. 调用 select_characters，预选角色让用户确认。
3. 写剧情脚本（write_script 到 output/scripts/story_xxx.md）：角色设定、故事线、情节点。
4. 基于剧情脚本生成分镜脚本 JSON（write_storyboard 到 output/storyboards/xxx.json），格式如下：
   ```json
   {
     "title": "黑客松传说",
     "characters": {
       "Jules": "粉色背心女生",
       "Peize": "黄色连帽衫男生"
     },
     "clips": [
       {
         "clip_index": 1,
         "description": "凌晨黑客松教室，粉色背心女生皱眉走向黄色连帽衫男生质问代码进度",
         "scene": "凌晨的黑客松教室",
         "scene_image": "/path/to/hackathon_room.png",
         "shot": {
           "camera": "中景",
           "action": "粉色背心女生皱眉走向黄色连帽衫男生，双手交叉质问",
           "lines": [
             {"speaker": "Jules", "voice": "young_female", "text": "代码写完了吗？"}
           ]
         }
       },
       {
         "clip_index": 2,
         "description": "黄色连帽衫男生惊慌回头，嘴角抽搐",
         "scene": "凌晨的黑客松教室",
         "scene_image": "/path/to/hackathon_room.png",
         "shot": {
           "camera": "特写",
           "action": "黄色连帽衫男生惊慌回头，嘴角抽搐",
           "lines": [
             {"speaker": "Peize", "voice": "young_male", "text": "还...还差一点！"}
           ]
         }
       },
       {
         "clip_index": 3,
         "description": "粉色背心女生坐到电脑前开始疯狂打字，屏幕代码飞速滚动",
         "scene": "同一间教室，屏幕前",
         "scene_image": "/path/to/hackathon_room.png",
         "shot": {
           "camera": "全景",
           "action": "粉色背心女生坐下疯狂打字，表情专注",
           "lines": [
             {"speaker": "narrator", "voice": "mature_male", "text": "键盘的敲击声回荡在空荡的教室里。"}
           ]
         }
       }
     ]
   }
   ```
5. **关键规则**：
   - 每个 clip = 1 个 shot = 1 个 6 秒视频（16:9 横屏）
   - **clip 结构**：
     - clip.description: 片段概括描述（直接用作视频 prompt）
     - shot.camera: 镜头景别（全景/中景/近景/特写等）
     - shot.action: 具体动作和表情描述
     - shot.lines（必填）: 台词/旁白数组，每条 {speaker, voice, text}：
       - speaker: 角色名或 'narrator'（旁白/OS）
       - voice: 声线标签，如 young_female、young_male、mature_male、mature_female、child 等
         同一个角色在整部作品中 voice 必须一致
       - text: 台词或旁白内容
   - **每个 shot 必须且只能有一个人说话**：lines 不能为空，所有条目的 speaker 必须相同（同一个角色或同一个 narrator）。
     纯画面镜头用 narrator 旁白描述画面。如果需要对话（A说→B回），拆成两个 clip。
   - **角色 = 外貌标签（服装+特征）**：如「粉色背心女生」「蓝衣服男人」
     同一套衣服 = 同一个角色，只需一个 asset，表情/动作在 shot.action 中描述
   - **shot.action 描述动作+表情**：「粉色背心女生皱眉走过来」「蓝衣服男人惊慌回头嘴角抽搐」
   - **scene_image**: 每个 clip 指定一张场景参考图，同一场景的 clips 用同一张图
   - 如果没有合适的场景图，先用 generate_asset 生成到 output/scenes/stylized/
6. 把分镜脚本展示给用户，确认后再生成首帧。

**Step 2: 生成首帧（条漫切割法）**
7. clip 数量必须是 4 的倍数。每 4 个 clip 调用一次 generate_storyboard_strip：
   - character_paths: 角色素材图路径
   - panel_descriptions: 4 个格子的画面描述，取每个 clip 的 shot.camera + shot.action
     每格描述要写清：景别、场景、角色外貌标签、动作姿态、表情
   - strip_index: 条漫编号（第1条=clip 1-4，第2条=clip 5-8）
   - output_dir: output/storyboards/frames
   该工具内部自动：生成4格无台词条漫 → 切割 → 放大 → 裁到16:9，同一条的 4 格天然角度不同。

**Step 3: 生成视频脚本**
8. 对每个 clip 基于首帧 + clip.description 写视频脚本，用 write_script 保存为独立 md 文件
   文件名固定为 output/storyboards/clip_scripts/clip_数字.md（如 clip_1.md、clip_2.md），不要用其他命名格式。
   md 内容包含：
   ```
   ## 画面描述
   （shot.camera + shot.action 的详细描述）
   ## 台词
   speaker: XXX | voice: young_female | 台词内容
   （必须有，纯画面镜头用 narrator 旁白）
   ## 视频 Prompt
   （简短视频 prompt，前 20 词最重要，格式：[动作] + [镜头运动] + [风格]）
   ```
   视频 prompt 规则：
   - 角色台词：「XXX说'台词'」；旁白：「Voiceover: 内容」
   - 例如：「粉色背心女生走向蓝衣男生说'代码写完了吗'。推近。动画风格。角色说中文。No background music.」
   - 例如：「粉色背心女生疯狂打字。Voiceover: 键盘的敲击声回荡在教室里。动画风格。No background music.」
   - 中文加「角色说中文。」，英文加「Characters speak English.」
   - **末尾必须加「No background music.」**

**Step 4: 生成视频**
9. 用 check_jobs 确认首帧都生成好后，对每个 clip 调用 generate_video_clip（可以一起发起），只传 clip_index：
   工具自动从 clip_scripts/clip_N.md 读取完整脚本作为 prompt，
   自动从 storyboards/frames/clip_N.png 读取首帧。

**Step 5: 合并视频**
10. 用 check_jobs 确认所有 clip 视频都生成完后，调用 merge_video_clips 合并为完整视频：
   - clip_paths: 按顺序排列的所有 clip 视频路径
   - output_path: output/videos/final_merged.mp4
   单独的 clip 文件保留不删除。

**禁止**：不要用 generate_asset 手动生成分镜帧/首帧图片。所有分镜帧必须且只能通过 generate_storyboard_strip 生成（自动切割+放大）。
generate_asset 只能用于生成场景背景图（output/scenes/stylized/）。
