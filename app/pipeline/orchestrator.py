from app.pipeline.artifacts import ArtifactStore
from app.pipeline.domain import (
    PipelineEvent,
    PipelineStage,
    ProjectSnapshot,
    ProjectStatus,
    ScriptCandidate,
)
from app.pipeline.policy import apply_policy, plan_revision
from app.pipeline.repository import PipelineRepository
from app.pipeline.stages.script import ScriptStage


class PipelineOrchestrator:
    def __init__(
        self,
        repository: PipelineRepository,
        script_stage: ScriptStage,
        artifacts: ArtifactStore,
    ):
        self.repository = repository
        self.script_stage = script_stage
        self.artifacts = artifacts

    def _event(
        self,
        project_id: str,
        run_id: str,
        stage: PipelineStage,
        event_type: str,
        payload: dict | None = None,
        candidate_id: str | None = None,
    ) -> None:
        self.repository.append_event(
            PipelineEvent(
                project_id=project_id,
                run_id=run_id,
                candidate_id=candidate_id,
                stage=stage,
                event_type=event_type,
                payload=payload or {},
            )
        )

    def _set_stage(self, run, project, stage: PipelineStage) -> None:
        run.current_stage = stage
        run.status = ProjectStatus.running
        project.status = ProjectStatus.running
        self.repository.update_run(run)
        self.repository.update_project(project)
        self._event(project.project_id, run.run_id, stage, "stage_started")

    def _finish_for_review(self, run, project) -> ProjectSnapshot:
        candidates = self.repository.list_candidates(run.run_id)
        best = max(candidates, key=lambda item: item.scorecard.overall_score)
        run.status = ProjectStatus.review_required
        run.current_stage = PipelineStage.review_required
        run.selected_candidate_id = best.candidate_id
        project.status = ProjectStatus.review_required
        self.repository.update_run(run)
        self.repository.update_project(project)
        self._event(
            project.project_id,
            run.run_id,
            PipelineStage.review_required,
            "review_required",
            {"best_candidate_id": best.candidate_id},
        )
        snapshot = self.repository.get_snapshot(project.project_id)
        if snapshot is None:
            raise RuntimeError("project disappeared before review")
        return snapshot

    def run_script_loop(self, run_id: str) -> ProjectSnapshot:
        run = self.repository.get_run(run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        project = self.repository.get_project(run.project_id)
        if project is None:
            raise KeyError(f"unknown project: {run.project_id}")

        try:
            self._set_stage(run, project, PipelineStage.briefing)
            brief = run.brief or self.script_stage.generate_brief(project)
            self.repository.save_brief(run.run_id, brief)
            self.artifacts.write_json(
                project.project_id,
                run.run_id,
                "brief.json",
                brief.model_dump(mode="json"),
            )
            self._event(
                project.project_id,
                run.run_id,
                PipelineStage.briefing,
                "stage_completed",
            )

            self._set_stage(run, project, PipelineStage.script_generating)
            script = self.script_stage.generate_script(brief)
            parent_candidate_id = None
            previous_score = None

            for version in range(1, run.policy.max_revisions + 2):
                self._set_stage(run, project, PipelineStage.script_scoring)
                scorecard = apply_policy(
                    self.script_stage.evaluate_script(brief, script),
                    run.policy,
                )
                candidate = ScriptCandidate(
                    run_id=run.run_id,
                    version=version,
                    parent_candidate_id=parent_candidate_id,
                    script=script,
                    scorecard=scorecard,
                )
                candidate_dir = f"candidates/v{version}"
                self.artifacts.write_json(
                    project.project_id,
                    run.run_id,
                    f"{candidate_dir}/script.json",
                    script.model_dump(mode="json"),
                )
                self.artifacts.write_json(
                    project.project_id,
                    run.run_id,
                    f"{candidate_dir}/score-script.json",
                    scorecard.model_dump(mode="json"),
                )
                self.repository.save_candidate(candidate)
                self._event(
                    project.project_id,
                    run.run_id,
                    PipelineStage.script_scoring,
                    "candidate_scored",
                    {
                        "version": version,
                        "overall_score": scorecard.overall_score,
                        "passed": scorecard.passed,
                    },
                    candidate.candidate_id,
                )

                if scorecard.passed:
                    run.status = ProjectStatus.script_approved
                    run.current_stage = PipelineStage.script_approved
                    run.selected_candidate_id = candidate.candidate_id
                    project.status = ProjectStatus.script_approved
                    self.repository.update_run(run)
                    self.repository.update_project(project)
                    self._event(
                        project.project_id,
                        run.run_id,
                        PipelineStage.script_approved,
                        "script_approved",
                        {"version": version, "score": scorecard.overall_score},
                        candidate.candidate_id,
                    )
                    snapshot = self.repository.get_snapshot(project.project_id)
                    if snapshot is None:
                        raise RuntimeError("project disappeared after script approval")
                    return snapshot

                improvement = (
                    scorecard.overall_score - previous_score
                    if previous_score is not None
                    else None
                )
                if improvement is not None and improvement < run.policy.minimum_improvement:
                    self._event(
                        project.project_id,
                        run.run_id,
                        PipelineStage.script_scoring,
                        "revision_stagnated",
                        {"improvement": improvement},
                        candidate.candidate_id,
                    )
                    return self._finish_for_review(run, project)

                if version > run.policy.max_revisions:
                    return self._finish_for_review(run, project)

                self._set_stage(run, project, PipelineStage.script_revising)
                revision = plan_revision(scorecard, run.policy)
                candidate.revision = revision
                self.repository.save_candidate(candidate)
                self.artifacts.write_json(
                    project.project_id,
                    run.run_id,
                    f"{candidate_dir}/revision.json",
                    revision.model_dump(mode="json"),
                )
                parent_candidate_id = candidate.candidate_id
                previous_score = scorecard.overall_score
                script = self.script_stage.revise_script(brief, script, revision)

            raise RuntimeError("script loop terminated without a final state")
        except Exception as exc:
            run.status = ProjectStatus.failed
            run.current_stage = PipelineStage.failed
            run.error = f"{type(exc).__name__}: {exc}"
            project.status = ProjectStatus.failed
            self.repository.update_run(run)
            self.repository.update_project(project)
            self._event(
                project.project_id,
                run.run_id,
                PipelineStage.failed,
                "pipeline_failed",
                {"error": run.error},
            )
            raise
