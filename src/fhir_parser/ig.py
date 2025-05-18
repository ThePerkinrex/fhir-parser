import json
import logging
from pathlib import Path
from queue import Queue
import re
from typing import Callable, Iterator, cast
import fhirspec

LOGGER = logging.getLogger(__name__)

def fhir_package_files(package_path: Path) -> Iterator[Path]:
    for file in (package_path / 'package').iterdir():
        if file.is_file() and file.suffix == '.json':
            yield file


def _process_profile(spec: fhirspec.FHIRSpec, resource) -> fhirspec.FHIRStructureDefinition | None:
    profile: fhirspec.FHIRStructureDefinition = fhirspec.FHIRStructureDefinition(spec, resource)
    for pattern in fhirspec.UNSUPPORTED_PROFILES:
        assert isinstance(profile.url, str)
        if re.search(pattern, profile.url) is not None:
            LOGGER.info(f'Skipping "{resource["url"]}"')
            return
    if not profile or not profile.name:
        raise Exception(f"No name for profile {profile}")
    if spec.found_profile(profile):
        profile.process_profile()
        profile.targetname = f"{profile.name}{profile.targetname}"
        print(f'Profile {profile.name} -> target: {profile.targetname}')
        return profile

def add_igs_to_spec(spec: fhirspec.FHIRSpec, ig_files: Iterator[Path]):
    profiles = []
    resource_queue = Queue()
    for file in ig_files:
        with open(file, encoding='utf-8') as f:
            parsed = json.load(f)
            if "resourceType" not in parsed:
                LOGGER.warning(f'Expecting "resourceType" to be present, but is not in {file}')
                continue
            resource_queue.put(parsed)
    while not resource_queue.empty():
        parsed = resource_queue.get()
        resourceType = parsed['resourceType']
        if resourceType == "Bundle":
            if "entry" in parsed:
                for e in parsed['entry']:
                    resource_queue.put(e['resource'])
        elif resourceType == "StructureDefinition":
            profiles.append(parsed)
        elif resourceType == "ValueSet":
            assert "url" in parsed
            spec.valuesets[parsed["url"]] = fhirspec.FHIRValueSet(spec, parsed)
        elif resourceType == "CodeSystem":
            assert "url" in parsed
            if "content" in parsed and "concept" in parsed:
                spec.codesystems[parsed["url"]] = fhirspec.FHIRCodeSystem(spec, parsed)
            else:
                LOGGER.warning(f"CodeSystem with no concepts: {parsed['url']}")
        else:
            LOGGER.warning(
                    f'Unknown resourceType {resourceType}'
                )

    LOGGER.info(
            f"Found {len(spec.valuesets)} ValueSets and "
            f"{len(spec.codesystems)} CodeSystems"
        )


    for prof in cast(Iterator[fhirspec.FHIRStructureDefinition],filter(lambda x: x is not None, map(lambda resource: _process_profile(spec, resource), profiles))):
        prof.finalize()
        if len(prof.elements_sequences) == 0:
            for item in prof.structure.snapshot[1:]:
                prof.elements_sequences.append(item["id"].split(".")[1])

    if spec.settings.WRITE_UNITTESTS:
        spec.parse_unit_tests()

    pass
