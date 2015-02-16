import tempfile

from nameko.testing.services import entrypoint_hook, dummy
from nameko.testing.utils import get_extension
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.session import Session

from nameko_sqlalchemy import OrmSession, ORM_DB_URIS_KEY


DeclBase = declarative_base(name='examplebase')


class ExampleModel(DeclBase):
    __tablename__ = 'example'
    id = Column(Integer, primary_key=True)
    data = Column(String)


class ExampleService(object):
    session = OrmSession(DeclBase)

    @dummy
    def write(self, value):
        obj = ExampleModel(data=value)
        self.session.add(obj)
        self.session.commit()
        return obj.id

    @dummy
    def read(self, id):
        return self.session.query(ExampleModel).get(id).data


def test_dependency_provider(container_factory):

    config = {
        ORM_DB_URIS_KEY: {
            'exampleservice:examplebase': 'sqlite:///:memory:'
        }
    }

    container = container_factory(ExampleService, config)
    container.start()

    session_provider = get_extension(container, OrmSession)

    # verify setup
    assert session_provider.db_uri == 'sqlite:///:memory:'

    # verify get_dependency
    worker_ctx = object()  # don't need a real worker context
    session = session_provider.get_dependency(worker_ctx)
    assert isinstance(session, Session)
    assert session_provider.sessions[worker_ctx] is session

    # verify multiple workers
    worker_ctx_2 = object()
    session_2 = session_provider.get_dependency(worker_ctx_2)
    assert session_provider.sessions == {
        worker_ctx: session,
        worker_ctx_2: session_2
    }

    # verify teardown
    session.add(ExampleModel())
    assert session.new
    session_provider.worker_teardown(worker_ctx)
    assert worker_ctx not in session_provider.sessions
    assert not session.new  # session.close() rolls back new objects


def test_end_to_end(container_factory):

    # create a temporary database
    db_uri = 'sqlite:///{}'.format(tempfile.NamedTemporaryFile().name)
    engine = create_engine(db_uri)
    ExampleModel.metadata.create_all(engine)

    config = {
        ORM_DB_URIS_KEY: {
            'exampleservice:examplebase': db_uri
        }
    }

    container = container_factory(ExampleService, config)
    container.start()

    # write through the service
    with entrypoint_hook(container, "write") as write:
        pk = write("foobar")

    # verify changes written to disk
    entries = list(engine.execute('SELECT data FROM example LIMIT 1'))
    assert entries == [('foobar',)]

    # read through the service
    with entrypoint_hook(container, "read") as read:
        assert read(pk) == "foobar"
