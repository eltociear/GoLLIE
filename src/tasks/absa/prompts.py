from typing import List, Optional

from ..utils_typing import Name, String, Template, Value, dataclass


"""Relation definitions

The relation definitions are derived from the official SemEval-2015 ABSA Restaurant Reviews guidelines:
https://alt.qcri.org/semeval2015/task12/data/uploads/semeval2015_absa_restaurants_annotationguidelines.pdf
https://alt.qcri.org/semeval2015/task12/
"""


@dataclass
class Opinion(Template):
    """{absa_opinion}"""

    opinion_target_expression: Optional[str]
    """{absa_opinion_target_expression}"""

    entity_label: str
    """{absa_entity_label}"""
