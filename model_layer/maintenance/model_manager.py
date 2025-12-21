from model_layer.maintenance.skills_merge import merge_skills
from model_layer.storage.history import History


class ModelManager:
    """
    this class is responsible for the maintaining of the model.
    """

    def __init__(self, model, skills, goals, constraints, abstraction_mapping=lambda x: x):
        self.model = model  # I guess it will be a pddl format or somthing like that
        self.skills = skills
        self.abstraction_mapping = abstraction_mapping
        self.goals = goals
        self.constraints = constraints
        self.history = History()

    def model_expansion(self, new_info):
        """
        given a model, and new information that the model does not include, generate a new model that included the new information.
        For example, if the model does not know a ball is, but it knows that objects has location and they can by placed on
        other objects, this function will return a model that will have the ball location and if hte ball is on other objects.

        currently this will return the old model, and will not update the model.
        """
        return self.model

    def model_restriction(self, restriction):
        """
        given a model and a restriction, generate a submodel that relevant to the restriction.
        For example, if you need to bake a cake, your model for this task should not include the skills of changing a tire
        on your car.

        currently this will return the old model
        """
        return self.model

    def model_structure_update(self, history):
        """
        given a model and history, change the model structure and return it.

        currently this will return the old model
        """
        return self.model

    def bayesian_parameter_update(self, history):
        """
        given a model and history, change the model parameters based on bayes law and return it.
        """
        return self.model

    def merge_skills(self, other_skills):
        """
        create a mapping between skill from  model A and skills from  model B.

        currently this creates a straight linear map for A to B, ie A_skills[i]=B_skills[i].
        """
        return merge_skills(self.skills, other_skills)
