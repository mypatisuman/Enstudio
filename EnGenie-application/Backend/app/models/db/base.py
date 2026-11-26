from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Text, DateTime

Base = declarative_base()

class DBWrapper:
    Model = Base
    Column = Column
    Integer = Integer
    String = String
    Text = Text
    DateTime = DateTime
    
    def __init__(self):
        self.session = None

db = DBWrapper()
