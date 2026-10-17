"""人脸聚类与最佳图片匹配工具。

输入 N 张图片，输出去重后的人物列表，每个人物附带最佳配对图片。

用法：
    from src.tools.face_matcher import match_faces

    results = match_faces(["img1.jpg", "img2.jpg", "img3.jpg"])
    for person in results:
        print(person.person_id, person.best_face_path, person.best_image_path)
"""

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel

from src.providers.http import image_part
from src.tools.gemini_text import analyze_multimodal
from src.tools.person_detector import FaceBox, detect_faces

logger = logging.getLogger(__name__)

# 余弦相似度阈值，高于此值认为是同一个人
DEFAULT_SIMILARITY_THRESHOLD = 0.4


class _ClusterMergeResult(BaseModel):
    """视觉模型判断哪些聚类应该合并。"""
    groups: list[list[int]]  # 应该合并的聚类索引分组
    reason: str


def _cluster_embeddings(embeddings: np.ndarray, threshold: float) -> np.ndarray:
    """用 DBSCAN + cosine 距离对 InsightFace 的 normed_embedding 聚类。

    Args:
        embeddings: (N, 512) 的 L2 归一化 embedding 矩阵。
        threshold: 余弦相似度阈值，转换为 eps = 1 - threshold。

    Returns:
        长度为 N 的标签数组。label=-1 表示噪声点。
    """
    from sklearn.cluster import DBSCAN

    if len(embeddings) == 1:
        return np.array([0])

    # cosine 距离 = 1 - cosine_similarity
    # eps = 1 - threshold: 相似度 > threshold 的归为同一簇
    eps = 1.0 - threshold

    clustering = DBSCAN(eps=eps, min_samples=1, metric="cosine")
    labels = clustering.fit_predict(embeddings)
    return labels


def _crop_face_bytes(occ: "FaceOccurrence", padding: float = 0.3) -> bytes:
    """从原图中裁剪人脸区域，返回 JPEG bytes。"""
    img = Image.open(occ.image_path)
    w, h = img.size
    face = occ.face
    pad_x = face.width * padding
    pad_y = face.height * padding
    x1 = max(0, int(face.x1 - pad_x))
    y1 = max(0, int(face.y1 - pad_y))
    x2 = min(w, int(face.x2 + pad_x))
    y2 = min(h, int(face.y2 + pad_y))
    cropped = img.crop((x1, y1, x2, y2))
    buf = io.BytesIO()
    cropped.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _get_cluster_representative(cluster: list["FaceOccurrence"]) -> "FaceOccurrence":
    """选离聚类中心最近的 occurrence 作为代表。"""
    if len(cluster) == 1:
        return cluster[0]
    embs = np.stack([o.face.embedding for o in cluster])
    center = embs.mean(axis=0)
    center = center / np.linalg.norm(center)
    sims = embs @ center
    return cluster[int(np.argmax(sims))]


def _merge_clusters_with_llm(
    clusters: list[list["FaceOccurrence"]],
) -> list[list["FaceOccurrence"]]:
    """用视觉模型判断哪些聚类应该合并（同一人被 embedding 分到了不同聚类）。

    每个聚类取 bbox 最大的人脸作为代表，全部发给视觉模型做比对，
    返回合并后的聚类列表。

    Args:
        clusters: embedding 聚类结果。

    Returns:
        合并后的聚类列表。
    """
    if len(clusters) <= 1:
        return clusters

    # 每个聚类取代表脸（bbox 最大）
    representatives = [_get_cluster_representative(c) for c in clusters]

    # 构建 contents: 每个聚类的代表脸 + prompt
    contents: list = []
    for i, rep in enumerate(representatives):
        contents.append(image_part(_crop_face_bytes(rep), "image/jpeg"))

    index_desc = "\n".join(f"Image {i + 1}: cluster #{i}" for i in range(len(clusters)))
    contents.append(
        f"You are given {len(clusters)} face images, each representing a different cluster:\n"
        f"{index_desc}\n\n"
        "These clusters were created by embedding similarity, but the algorithm may have "
        "split the SAME person into multiple clusters.\n\n"
        "Compare all faces carefully. If two or more clusters show the SAME person, "
        "they should be merged into one group.\n"
        "If all clusters are different people, each gets its own group.\n\n"
        "Return groups as a list of cluster index lists (0-based).\n"
        "Example: if cluster #0 and #2 are the same person, cluster #1 is a different person "
        "→ groups: [[0,2],[1]]"
    )

    try:
        result = analyze_multimodal(
            contents=contents,
            schema=_ClusterMergeResult,
            max_retries=2,
        )
        # 验证索引合法性
        all_indices = [idx for group in result.groups for idx in group]
        expected = set(range(len(clusters)))
        if set(all_indices) != expected or len(all_indices) != len(expected):
            logger.warning(f"LLM 返回索引不合法: {result.groups}，跳过合并")
            return clusters

        # 执行合并
        merged: list[list[FaceOccurrence]] = []
        for group in result.groups:
            combined: list[FaceOccurrence] = []
            for idx in group:
                combined.extend(clusters[idx])
            merged.append(combined)

        logger.info(f"LLM 合并: {len(clusters)} 个聚类 -> {len(merged)} 个人物 ({result.reason})")
        return merged
    except Exception as e:
        logger.warning(f"LLM 合并失败，跳过: {e}")
        return clusters


@dataclass
class FaceOccurrence:
    """一个人脸在某张图中的出现记录。"""
    face: FaceBox
    image_path: Path
    face_index: int  # 该人脸在这张图中的序号


@dataclass
class PersonMatch:
    """去重后的一个人物，附带最佳配对信息。"""
    person_id: int
    best_face: FaceBox
    best_image_path: Path
    best_face_index: int
    best_face_crop_path: Path | None = None
    occurrences: list[FaceOccurrence] = field(default_factory=list)

    @property
    def appearance_count(self) -> int:
        return len(self.occurrences)


# 人脸质量过滤阈值
MIN_FACE_SIZE = 40         # 宽或高小于此像素数的人脸丢弃
MIN_FACE_AREA = 2500       # 面积（px²）小于此值的丢弃
MIN_SHARPNESS = 15.0       # 拉普拉斯方差低于此值视为模糊


def _is_face_quality_ok(
    face: FaceBox,
    image_path: Path,
    min_size: int = MIN_FACE_SIZE,
    min_area: float = MIN_FACE_AREA,
    min_sharpness: float = MIN_SHARPNESS,
) -> bool:
    """检查人脸是否满足尺寸和清晰度要求。"""
    # 尺寸过滤
    if face.width < min_size or face.height < min_size:
        return False
    if face.area < min_area:
        return False

    # 清晰度过滤：裁剪人脸区域计算拉普拉斯方差
    img = cv2.imread(str(image_path))
    if img is None:
        return False
    x1 = max(0, int(face.x1))
    y1 = max(0, int(face.y1))
    x2 = min(img.shape[1], int(face.x2))
    y2 = min(img.shape[0], int(face.y2))
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if laplacian_var < min_sharpness:
        return False

    return True


def match_faces(
    image_paths: list[str | Path],
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    confidence: float = 0.5,
) -> list[PersonMatch]:
    """从多张图片中检测人脸、聚类去重、为每个人选出最佳配对图片。

    最佳图片的选择标准：人脸检测框面积最大（通常意味着人物更完整、更清晰）。

    Args:
        image_paths: 图片路径列表。
        similarity_threshold: 人脸相似度阈值，高于此值视为同一人。
        confidence: 人脸检测置信度阈值。

    Returns:
        去重后的人物列表，按出现次数降序排列。
    """
    image_paths = [Path(p) for p in image_paths]

    # 1. 检测所有图片中的人脸
    all_occurrences: list[FaceOccurrence] = []
    for img_path in image_paths:
        if not img_path.exists():
            logger.warning(f"图片不存在，跳过: {img_path}")
            continue
        faces = detect_faces(img_path, confidence=confidence)
        for idx, face in enumerate(faces):
            if face.embedding is not None:
                if not _is_face_quality_ok(face, img_path):
                    logger.debug(
                        f"过滤低质量人脸: {img_path.name} face_{idx} "
                        f"({face.width:.0f}x{face.height:.0f})"
                    )
                    continue
                all_occurrences.append(FaceOccurrence(
                    face=face, image_path=img_path, face_index=idx,
                ))

    if not all_occurrences:
        logger.info("未检测到任何人脸（全部被质量过滤）")
        return []

    logger.info(f"共检测到 {len(all_occurrences)} 个有效人脸，开始聚类")

    # 2. 用 512 维 embedding 做层次聚类
    embeddings = np.stack([occ.face.embedding for occ in all_occurrences])
    labels = _cluster_embeddings(embeddings, similarity_threshold)

    clusters: list[list[FaceOccurrence]] = []
    for label_id in range(labels.max() + 1):
        cluster = [all_occurrences[i] for i in range(len(labels)) if labels[i] == label_id]
        if cluster:
            clusters.append(cluster)

    logger.info(f"聚类完成: {len(all_occurrences)} 个人脸 -> {len(clusters)} 个人物")

    # 3. 每个聚类选最佳配对：离池化中心最近的 embedding
    results: list[PersonMatch] = []
    for pid, cluster in enumerate(clusters):
        cluster_embeddings = np.stack([o.face.embedding for o in cluster])
        center = cluster_embeddings.mean(axis=0)
        center = center / np.linalg.norm(center)  # L2 归一化
        sims = cluster_embeddings @ center
        best_idx = int(np.argmax(sims))
        best = cluster[best_idx]
        results.append(PersonMatch(
            person_id=pid,
            best_face=best.face,
            best_image_path=best.image_path,
            best_face_index=best.face_index,
            occurrences=cluster,
        ))

    # 按出现次数降序
    results.sort(key=lambda p: p.appearance_count, reverse=True)
    # 重新编号
    for i, p in enumerate(results):
        p.person_id = i

    return results


def match_and_crop(
    image_paths: list[str | Path],
    output_dir: str | Path,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    confidence: float = 0.5,
    padding: float = 0.3,
) -> list[PersonMatch]:
    """检测、聚类、裁剪最佳人脸。

    在 match_faces 基础上，将每个人物的最佳人脸裁剪保存。

    Args:
        image_paths: 图片路径列表。
        output_dir: 裁剪输出目录。
        similarity_threshold: 人脸相似度阈值。
        confidence: 人脸检测置信度阈值。
        padding: 裁剪时边界框扩展比例。

    Returns:
        去重后的人物列表，best_face_crop_path 已填充。
    """
    from PIL import Image

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    persons = match_faces(image_paths, similarity_threshold, confidence)

    # 代表脸单独文件夹
    representatives_dir = output_dir / "representatives"
    representatives_dir.mkdir(parents=True, exist_ok=True)

    for person in persons:
        person_dir = output_dir / f"person_{person.person_id}"
        person_dir.mkdir(parents=True, exist_ok=True)

        # 裁剪所有出现的人脸
        for i, occ in enumerate(person.occurrences):
            img = Image.open(occ.image_path)
            w, h = img.size
            face = occ.face
            pad_x = face.width * padding
            pad_y = face.height * padding
            x1 = max(0, int(face.x1 - pad_x))
            y1 = max(0, int(face.y1 - pad_y))
            x2 = min(w, int(face.x2 + pad_x))
            y2 = min(h, int(face.y2 + pad_y))
            cropped = img.crop((x1, y1, x2, y2)).convert("RGB")
            crop_path = person_dir / f"{occ.image_path.stem}_face_{occ.face_index}.jpg"
            cropped.save(crop_path, quality=95)

            # 标记最佳人脸并复制到代表脸文件夹
            if occ.face is person.best_face:
                person.best_face_crop_path = crop_path
                rep_path = representatives_dir / f"person_{person.person_id}.jpg"
                cropped.save(rep_path, quality=95)

        logger.info(
            f"人物 {person.person_id}: 出现 {person.appearance_count} 次, "
            f"最佳来源 {person.best_image_path.name}, 目录 {person_dir}"
        )

    return persons
