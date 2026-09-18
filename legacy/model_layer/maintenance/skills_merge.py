def merge_skills(A_skills, B_skills):
    """
    create a mapping between skill from  model A and skills from  model B.

    currently this creates a straight linear map for A to B, ie A_skills[i]=B_skills[i].

    :param A_skills: list of skills in model A
    :param B_skills: list of skills in model B
    :return: mapping of skills from model A to model B
    """
    # Ensure lists are the same length to avoid silent data loss
    if len(A_skills) != len(B_skills):
        raise ValueError(
            f"Skill lists must be the same length. "
            f"A_skills has {len(A_skills)}, B_skills has {len(B_skills)}."
        )

    return dict(zip(A_skills, B_skills))
