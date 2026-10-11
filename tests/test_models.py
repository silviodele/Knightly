from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from knime_scheduler.models import Base, Environment, Run, Schedule, Workflow, WorkflowDependency


def test_create_full_graph():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        env = Environment(name="KNIME 5.3", knime_path="C:/knime-5.3", jvm_args=["-Xmx4g"])
        wf = Workflow(name="Report", file_path="data/workflows/report.knwf")
        wf.dependencies.append(WorkflowDependency(feature_id="org.knime.features.base.feature.group"))
        sched = Schedule(name="Ogni mattina", workflow=wf, environment=env, trigger_value="0 6 * * 1-5")
        sched.runs.append(Run())
        s.add(sched)
        s.commit()

        loaded = s.get(Schedule, sched.id)
        assert loaded.environment.name == "KNIME 5.3"
        assert loaded.workflow.dependencies[0].source == "detected"
        assert loaded.concurrency == "skip" and loaded.notify_on == ["failed"]
        assert loaded.runs[0].status == "queued"
