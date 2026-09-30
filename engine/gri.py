"""WCO General Rules of Interpretation used by the classifier.

The engine applies the rules as a decision order. It does not paraphrase the
entire legal text into a prompt. GRI 1 decides the heading from its terms and
the section or chapter notes. GRI 3(a) then prefers the subheading with the
more specific description. GRI 6 says those same rules apply at subheading level.
"""

GRI_1 = (
    "GRI 1: classification is determined by the terms of the headings and the "
    "relative Section or Chapter Notes."
)
GRI_3A = (
    "GRI 3(a): the heading or subheading with the more specific description "
    "is preferred to one with a general description."
)
GRI_6 = "GRI 6: GRI 1 to 5 apply at subheading level within the chosen heading."
