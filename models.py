import json
import os
import typing

import mongoengine as me

CURRENT_DIRECTORY = os.path.dirname(__file__)
PATH_JSON_COURSES = os.path.join(CURRENT_DIRECTORY, 'data', 'courses.json')

DB_NAME = 'ubcapi'

SCORE_THRESHOLD = 4
MAX_NAME_COUNT = 10


class CourseNameScore(me.EmbeddedDocument):
    name = me.StringField(required=True)
    score = me.IntField(min_value=1, default=1)

    def clean(self):
        self.name = self.name.strip()

    def __lt__(self, other):
        return self.score > other.score

    # FOR DEBUGGING
    def __str__(self):
        return "{0} : {1}".format(self.name, self.score)

    def __repr__(self):
        return "{0} : {1}".format(self.name, self.score)


class AbstractCourse(me.Document):
    code = me.StringField(primary_key=True)
    name = me.StringField(required=True)
    course_name_scores = me.ListField(
        me.EmbeddedDocumentField(CourseNameScore))

    def clean(self):
        self.name = self.name.strip()

    # FOR DEBUGGING
    def __str__(self):
        return "{0} : {1} -> {2}".format(self.code, self.name, self.course_name_scores)

    def __repr__(self):
        return "{0} : {1} -> {2}".format(self.code, self.name, self.course_name_scores)

    meta = {
        'allow_inheritance': True,
        'abstract': True
    }


class Course(AbstractCourse):
    meta = {
        'collection': 'courses-live'
    }


class AbstractLog(me.Document):
    combined_timestamp = me.StringField(required=True)
    courses = me.MapField(field=me.StringField())

    meta = {
        'allow_inheritance': True,
        'abstract': True
    }

class Log(AbstractLog):
    meta = {
        'collection': 'logs-live'
    }

class DAOWrapper:
    def __init__(self, db_user, db_password, db_host, db_port, generic_course = Course, generic_log = Log):
        uri = "mongodb://{0}:{1}@{2}:{3}/{4}".format(
            db_user,
            db_password,
            db_host,
            db_port,
            DB_NAME
        )

        # NOTE: 'connect=False' is to avoid connection pooling sine PyMongo is not fork-safe
        me.connect(host=uri, connect=False, maxPoolSize=1)
        self.generic_course = generic_course
        self.generic_log = generic_log

    def insert_courses(self, courses: typing.List[AbstractCourse]):
        try:
            self.generic_course.objects.insert(courses, write_concern={'continue_on_error': True})
        except me.NotUniqueError:
            pass

    def insert_course(self, course: AbstractCourse) -> AbstractCourse:
        return course.save()

    # TODO: Way too much logic in this method. 
    def update_course(self, _code: str, _name: str) -> AbstractCourse:
        c: AbstractCourse = self.get_course(_code)
        # If the course does not exist in the DB at all
        if c is None:
            c = self.generic_course(code=_code, name=_name)
        else:
            # If the current course name is not the same as the updated one
            if c.name != _name:
                current_course_names = list(
                    map(lambda cs: cs.name,  c.course_name_scores))

                # If the updated course name is in the list of suggestions already
                if _name in current_course_names:
                    i = current_course_names.index(_name)
                    cns: CourseNameScore = c.course_name_scores[i]
                    cns.score = cns.score + 1

                    # The new course name has earned enough to become the default course name for this course
                    if cns.score > SCORE_THRESHOLD:
                        c.name = cns.name
                        c.course_name_scores.pop(i)

                    c.course_name_scores.sort()
                else:
                    # Pop off the least popular course name
                    # NOTE: Suggested course names are sorted in order of descending popularity
                    if len(c.course_name_scores) > MAX_NAME_COUNT - 1:
                        c.course_name_scores.pop()
                    
                    c.course_name_scores.append(CourseNameScore(name=_name))
        c.save()
        return c

    def get_course(self, course_code: str) -> typing.Optional[Course]:
        try:
            return self.generic_course.objects.get(pk=course_code)
        except me.DoesNotExist:
            return None

    def get_courses(self, course_codes: typing.List[str]) -> typing.List[AbstractCourse]:
        return list(self.generic_course.objects(pk__in=course_codes))

    def insert_log(self, log: AbstractLog) -> AbstractLog:
        self.generic_log.objects.insert(log)
    
    def drop_collection(self, collection: me.Document):
        collection.drop_collection()


def insert_courses_from_dict(dao_wrapper: DAOWrapper, course_dict: dict):
    def tuple_to_doc(course_tuple):
        return dao_wrapper.generic_course(code=course_tuple[0], name=course_tuple[1])
    
    courses = list(map(tuple_to_doc, course_dict.items()))
    dao_wrapper.insert_courses(courses)

def insert_courses_from_json(dao_wrapper: DAOWrapper, file_path: str):
    course_dictionary = {}
    with open(file_path, 'r') as f:
        course_dictionary = json.load(f)
    
    insert_courses_from_dict(dao_wrapper, course_dictionary)


if __name__ == '__main__':
    dao_wrapper = DAOWrapper(
        os.environ['DB_USER'],
        os.environ['DB_PASSWORD'],
        os.environ['DB_HOST'],
        os.environ['DB_PORT'],
        Course,
        Log
    )
    insert_courses_from_json(dao_wrapper, PATH_JSON_COURSES)
