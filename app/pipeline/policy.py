from app.pipeline.domain import PipelinePolicy, RevisionAction, Scorecard


SCRIPT_DIMENSION_WEIGHTS = {
    "hook": 0.20,
    "theme_fit": 0.15,
    "narrative_structure": 0.15,
    "specificity": 0.15,
    "emotion_curve": 0.10,
    "speakability": 0.10,
    "visualizability": 0.10,
    "safety": 0.05,
}


THEME_PROFILES = {
    "motivational": {
        "structure": "困境或共鸣 → 认知转折 → 具体行动 → 情绪抬升 → 余韵或号召",
        "focus": "具体细节、可执行行动、逐步上升的情绪曲线和可记忆结尾",
    },
    "comedy": {
        "structure": "建立预期 → 加强预期 → 错位或误导 → 包袱 → 回扣",
        "focus": "短铺垫、明确预期差、及时包袱以及文案画面共同服务笑点",
    },
    "contrast": {
        "structure": "展示 A → 强化预期 → 揭示 B → 对比证据 → 总结冲击",
        "focus": "清晰的 A/B 差异、揭示前悬念和镜头声音字幕共同强调转折",
    },
}


def calculate_overall_score(scorecard: Scorecard) -> float:
    by_name = {dimension.name: dimension for dimension in scorecard.dimensions}
    return round(
        sum(by_name[name].score * weight for name, weight in SCRIPT_DIMENSION_WEIGHTS.items()),
        2,
    )


def apply_policy(scorecard: Scorecard, policy: PipelinePolicy) -> Scorecard:
    by_name = {dimension.name: dimension for dimension in scorecard.dimensions}
    missing = set(SCRIPT_DIMENSION_WEIGHTS) - set(by_name)
    if missing:
        raise ValueError(f"scorecard is missing dimensions: {sorted(missing)}")

    for name, weight in SCRIPT_DIMENSION_WEIGHTS.items():
        by_name[name].weight = weight
    scorecard.overall_score = calculate_overall_score(scorecard)
    scorecard.passed = scorecard.overall_score >= policy.script_threshold and all(
        by_name[name].score >= policy.critical_dimension_threshold
        for name in policy.critical_dimensions
    )
    return scorecard


def plan_revision(scorecard: Scorecard, policy: PipelinePolicy) -> RevisionAction:
    weak_dimensions = sorted(
        (
            dimension
            for dimension in scorecard.dimensions
            if dimension.score < (
                policy.critical_dimension_threshold
                if dimension.name in policy.critical_dimensions
                else policy.script_threshold
            )
        ),
        key=lambda dimension: dimension.score,
    )
    targets = weak_dimensions[:3] or sorted(
        scorecard.dimensions, key=lambda dimension: dimension.score
    )[:1]
    instructions = [dimension.action for dimension in targets if dimension.action]
    return RevisionAction(
        reason=f"脚本综合分 {scorecard.overall_score:.1f}，未达到 {policy.script_threshold:.1f}",
        target_dimensions=[dimension.name for dimension in targets],
        instructions=instructions or ["保留核心事实，针对最低分维度重写脚本"],
    )
