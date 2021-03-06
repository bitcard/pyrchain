import logging
import re
from typing import Optional, List, Union
from grpc import Channel

from .crypto import PrivateKey
from .util import create_deploy_data

from .pb.DeployServiceCommon_pb2 import DataAtNameQuery
from .pb.DeployServiceV1_pb2 import ListeningNameDataPayload as Data, DeployResponse, ListeningNameDataResponse
from .pb.DeployServiceV1_pb2_grpc import (DeployServiceStub)
from .pb.ProposeServiceV1_pb2_grpc import (ProposeServiceStub)
from .pb.ProposeServiceV1_pb2 import ProposeResponse
from .pb.ProposeServiceCommon_pb2 import PrintUnmatchedSendsQuery

from .pb.RhoTypes_pb2 import (Par, Expr, GUnforgeable, GDeployId)

GRPC_Response_T = Union[ProposeResponse, DeployResponse, ListeningNameDataResponse]

propose_result_match = re.compile(r'Success! Block (?P<block_hash>[0-9a-f]+) created and added.')

class RClientException(Exception):

    def _init__(self, message: str):
        super().__init__(message)


class DataQueries:

    @staticmethod
    def public_names(names: List[str]) -> Par:
        exprs = [Expr(g_string=n) for n in names]
        return Par(exprs=exprs)

    @staticmethod
    def deploy_id(deploy_id: bytes) -> Par:
        g_deploy_id = GDeployId(sig=deploy_id)
        g_unforgeable = GUnforgeable(g_deploy_id_body=g_deploy_id)
        return Par(unforgeables=[g_unforgeable])


class RClient:

    def __init__(self, channel: Channel):
        self.channel = channel

    def _check_response(self, response: GRPC_Response_T):
        logging.debug('gRPC response: %s', str(response))
        if response.WhichOneof("message") == 'error':
            raise RClientException('\n'.join(response.error.messages))

    def deploy(
        self,
        key: PrivateKey,
        term: str,
        phlo_price: int,
        phlo_limit: int,
        valid_after_block_no: int = -1,
        timestamp_millis: int = -1,
    ) -> str:
        deploy_data = create_deploy_data(
            key, term, phlo_price, phlo_limit, valid_after_block_no, timestamp_millis
        )
        stub = DeployServiceStub(self.channel)
        response = stub.doDeploy(deploy_data)
        self._check_response(response)
        # sig of deploy data is deployId
        return deploy_data.sig.hex()

    def propose(self) -> str:
        stub = ProposeServiceStub(self.channel)
        response: ProposeResponse = stub.propose(PrintUnmatchedSendsQuery(printUnmatchedSends=True))
        self._check_response(response)
        match_result = propose_result_match.match(response.result)
        assert match_result is not None
        return match_result.group("block_hash")

    def get_data_at_name(self, par: Par, depth: int = -1) -> Data:
        query = DataAtNameQuery(depth=depth, name=par)
        stub = DeployServiceStub(self.channel)
        response = stub.listenForDataAtName(query)
        self._check_response(response)
        wrapped = response.payload
        return Data.FromString(wrapped.SerializeToString())

    def get_data_at_public_names(self, names: List[str], depth: int = -1) -> Optional[Data]:
        return self.get_data_at_name(DataQueries.public_names(names), depth)

    def get_data_at_deploy_id(self, deploy_id: bytes, depth: int = -1) -> Optional[Data]:
        return self.get_data_at_name(DataQueries.deploy_id(deploy_id), depth)
