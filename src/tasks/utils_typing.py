from __future__ import annotations
from dataclasses import dataclass as org_dataclass
import inspect
import math
import random
from typing import Any, Dict, List, Tuple, Type, Union
from copy import deepcopy
from jinja2 import Template

import numpy as np


def dataclass(
    cls=None,
    /,
    *,
    init=True,
    repr=True,
    eq=False,
    order=False,
    unsafe_hash=False,
    frozen=False,
):
    return org_dataclass(
        cls,
        init=init,
        repr=repr,
        eq=eq,
        order=order,
        unsafe_hash=unsafe_hash,
        frozen=frozen,
    )


@dataclass
class Entity:
    """A general class to represent entities."""

    span: str

    def __eq__(self: Entity, other: Entity) -> bool:
        return type(self) == type(other) and self.span == other.span


@dataclass
class Value:
    """A general class to represent values."""

    span: str

    def __eq__(self: Value, other: Value) -> bool:
        return type(self) == type(other) and self.span == other.span


@dataclass
class Relation:
    """A general class to represent relations."""

    arg1: str
    arg2: str

    def __eq__(self: Value, other: Value) -> bool:
        return (
            type(self) == type(other)
            and self.arg1 == other.arg1
            and self.arg2 == other.arg2
        )


@dataclass
class Event:
    """A general class to represent events."""

    mention: str

    def __eq__(self: Event, other: Event) -> bool:
        return type(self) == type(other) and self.mention == other.mention

    def __and__(self: Event, other: Event) -> Event:
        attrs = {
            attr: []
            for attr, _ in inspect.getmembers(self)
            if not (attr.startswith("__") or attr in ["mention", "subtype"])
        }
        if self == other:
            for attr in attrs.keys():
                self_values = getattr(self, attr)
                other_values = deepcopy(getattr(other, attr))
                for value in self_values:
                    if value in other_values:
                        attrs[attr].append(value)
                        other_values.pop(other_values.index(value))

        return type(self)(mention=self.mention, **attrs)

    def __len__(self: Event) -> int:
        attrs = {
            attr: values
            for attr, values in inspect.getmembers(self)
            if not (attr.startswith("__") or attr == "mention")
        }
        _len = 0
        for values in attrs.values():
            _len += len(values)

        return _len


class Scorer:
    """An abstract class for scorers."""

    def __call__(self, reference: Any, predictions: Any) -> Dict[str, float]:
        raise NotImplementedError("This method must be implemented.")

    def _filter_valid_types(self, elems: List[Any]) -> List[Union[Entity, Value]]:
        return [
            elem
            for elem in elems
            if any(isinstance(elem, _type) for _type in self.valid_types)
        ]


class DatasetLoader:
    """An abstract class for dataset loaders."""

    def __iter__(self):
        for elem in self.elements.values():
            yield elem

    def __len__(self):
        return len(self.elements)

    def __getitem__(self, idx: Union[int, str]) -> Dict[str, Any]:
        if isinstance(idx, int):
            return list(self.elements.values())[idx]  # Not very efficient
        else:
            return self.elements[idx]


class Sampler:
    """An abstract class for example sampling."""

    def __init__(self,
        dataset_loader: DatasetLoader,
        task: str = None,
        split: str = "train",
        parallel_instances: Union[int, Tuple[int, int]] = 1,
        max_guidelines: int = -1,
        guideline_dropout: float = 0.0,
        seed: float = 0,
        prompt_template: str = "templates/prompt.txt",
        ensure_positives_on_train: bool = True,
        sample_only_gold_guidelines: bool = False,
        dataset_name: str = None,
        scorer: str = None,
        task_definitions: List[Type] = None,
        task_target: str = "labels",
        **kwargs,
    ) -> None:
        self.loader = dataset_loader
        self.task = task
        assert split in [
            "train",
            "dev",
            "test",
        ], f"{split} must be either 'train', 'dev' or 'test'."
        self.split = split
        if isinstance(parallel_instances, int):
            parallel_instances = (1, parallel_instances)
        self.parallel_instances = tuple(parallel_instances)
        self.guideline_dropout = guideline_dropout
        self.seed = seed
        if not task_definitions or not len(task_definitions):
            raise ValueError("task_definitions argument must not be None or empty")
        self.task_definitions = task_definitions
        self.task_target = task_target

        if max_guidelines < 0 or max_guidelines > len(self.task_definitions):
            self.max_guidelines = len(self.task_definitions)
        else:
            self.max_guidelines = max_guidelines
        self.ensure_positives_on_train = ensure_positives_on_train
        self.sample_only_gold_guidelines = sample_only_gold_guidelines

        with open(prompt_template, "rt") as f:
            self.template = Template(f.read())

        self.dataset_name = dataset_name
        self.scorer_cls = scorer
    
    def _sample(self, instances):
        if self.sample_only_gold_guidelines:
            guidelines = [
                definition
                for definition in self.task_definitions
                if any(
                    isinstance(ann, definition)
                    for inst in instances
                    for ann in inst[self.task_target]
                )
            ]
            random.shuffle(guidelines)
            splits = math.ceil(len(guidelines) / self.max_guidelines)
            for i in range(splits):
                _guidelines = guidelines[
                    i * self.max_guidelines : (i + 1) * self.max_guidelines
                ]
                _ann = [
                    ann
                    for inst in instances
                    for ann in inst[self.task_target]
                    if type(ann) in _guidelines
                ]
                _text = " ".join([inst["text"] for inst in instances]).strip()

                yield {
                    "ids": [inst["id"] for inst in instances],
                    "task_id": f"{self.dataset_name}_{self.task}",
                    "scorer_cls": self.scorer_cls,
                    "labels": [ann.__repr__() for ann in _ann],
                    "text": self.template.render(
                        guidelines=[
                            inspect.getsource(definition) for definition in _guidelines
                        ],
                        text=_text,
                        annotations=_ann,
                    ),
                }
        elif self.split == "train":
            positive_guidelines = {
                type(ann) for inst in instances for ann in inst[self.task_target]
            }
            # Assign a probability distribution that helps positive classes
            # if ensure_positives_on_train is True
            p = np.asarray(
                [
                    (
                        5.0
                        if _def in positive_guidelines and self.ensure_positives_on_train
                        else 0.0
                    )
                    for _def in self.task_definitions
                ]
            )
            p += 1.0 / p.shape[0]
            p /= p.sum()
            _guidelines = np.random.choice(
                np.asarray(self.task_definitions),
                size=(self.max_guidelines,),
                replace=False,
                p=p,
            ).tolist()
            # Apply guideline dropout
            _guidelines = [
                _def
                for _def in _guidelines
                if random.random() > self.guideline_dropout
                or (_def in positive_guidelines and self.ensure_positives_on_train)
            ]
            _ann = [
                ann
                for inst in instances
                for ann in inst[self.task_target]
                if type(ann) in _guidelines
            ]
            _text = " ".join([inst["text"] for inst in instances]).strip()
            yield {
                "ids": [inst["id"] for inst in instances],
                "task_id": f"{self.dataset_name}_{self.task}",
                "scorer_cls": self.scorer_cls,
                "labels": [ann.__repr__() for ann in _ann],
                "text": self.template.render(
                    guidelines=[
                        inspect.getsource(definition) for definition in _guidelines
                    ],
                    text=_text,
                    annotations=_ann,
                ),
            }
        else:
            guidelines = [definition for definition in self.task_definitions]
            random.shuffle(guidelines)
            splits = math.ceil(len(guidelines) / self.max_guidelines)
            for i in range(splits):
                _guidelines = guidelines[
                    i * self.max_guidelines : (i + 1) * self.max_guidelines
                ]
                _ann = [
                    ann
                    for inst in instances
                    for ann in inst[self.task_target]
                    if type(ann) in _guidelines
                ]
                _text = " ".join([inst["text"] for inst in instances]).strip()

                yield {
                    "ids": [inst["id"] for inst in instances],
                    "task_id": f"{self.dataset_name}_{self.task}",
                    "scorer_cls": self.scorer_cls,
                    "labels": [ann.__repr__() for ann in _ann],
                    "text": self.template.render(
                        guidelines=[
                            inspect.getsource(definition) for definition in _guidelines
                        ],
                        text=_text,
                        annotations=_ann,
                    ),
                }

    def __iter__(self):
        random.seed(self.seed)
        instances = []
        total_inst = random.randint(*self.parallel_instances)
        prev_id = None
        for elem in self.loader:
            # Prevent mixing sentences from different documents. TODO: generalize
            if (len(instances) == total_inst) or (
                prev_id is not None and elem["doc_id"] != prev_id
            ):
                for samp in self._sample(instances):
                    yield samp
                instances = []
                total_inst = random.randint(*self.parallel_instances)

            instances.append(elem)
            prev_id = elem["doc_id"]

        if len(instances):
            for samp in self._sample(instances):
                yield samp
