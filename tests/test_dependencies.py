import zipfile

from knime_scheduler.dependencies import (
    Dependency,
    DependencyStatus,
    check_dependencies,
    extract_dependencies,
    installed_features,
)


def node_settings(feature_id: str, name: str, version: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<config xmlns="http://www.knime.org/2008/09/XMLConfig" key="settings.xml">
<entry key="factory" type="xstring" value="some.NodeFactory"/>
<entry key="node-feature-name" type="xstring" value="{name}"/>
<entry key="node-feature-symbolic-name" type="xstring" value="{feature_id}"/>
<entry key="node-feature-vendor" type="xstring" value="KNIME AG, Zurich, Switzerland"/>
<entry key="node-feature-version" type="xstring" value="{version}"/>
<config key="model"><entry key="node-feature-symbolic-name" type="xstring" value="ignorato"/></config>
</config>"""


def make_knwf(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("WF/workflow.knime", "<config/>")
        zf.writestr("WF/CSV Reader (#1)/settings.xml",
                    node_settings("org.knime.features.base.feature.group", "KNIME Core", "5.2.0.v2023"))
        zf.writestr("WF/Python Script (#2)/settings.xml",
                    node_settings("org.knime.features.python3.scripting.feature.group", "KNIME Python", "5.2.1"))
        # nodo dentro un metanodo, stessa feature ma versione piu' alta
        zf.writestr("WF/Meta (#3)/Row Filter (#3:1)/settings.xml",
                    node_settings("org.knime.features.base.feature.group", "KNIME Core", "5.3.0"))
        # nodo senza info di feature (es. workflow molto vecchi)
        zf.writestr("WF/Old (#4)/settings.xml", "<config><entry key='factory' value='x'/></config>")


def test_extract_dependencies(tmp_path):
    knwf = tmp_path / "wf.knwf"
    make_knwf(knwf)
    deps = extract_dependencies(knwf)
    assert [d.feature_id for d in deps] == [
        "org.knime.features.base.feature.group",
        "org.knime.features.python3.scripting.feature.group",
    ]
    assert deps[0].version == "5.3.0" and deps[0].name == "KNIME Core"


def test_installed_features_and_check(tmp_path):
    features = tmp_path / "features"
    features.mkdir()
    (features / "org.knime.features.base_5.3.1.v202405").mkdir()
    (features / "org.knime.features.python3.scripting_5.1.0.v202306").mkdir()

    installed = installed_features(tmp_path)
    assert installed["org.knime.features.base.feature.group"] == "5.3.1.v202405"

    required = [
        Dependency("org.knime.features.base.feature.group", version="5.3.0"),
        Dependency("org.knime.features.python3.scripting.feature.group", version="5.2.1"),
        Dependency("com.example.missing.feature.group", version="1.0.0"),
    ]
    statuses = [c.status for c in check_dependencies(required, installed)]
    assert statuses == [DependencyStatus.OK, DependencyStatus.OUTDATED, DependencyStatus.MISSING]
