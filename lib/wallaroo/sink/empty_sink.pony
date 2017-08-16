use "collections"
use "wallaroo/boundary"
use "wallaroo/ent/data_receiver"
use "wallaroo/core"
use "wallaroo/initialization"
use "wallaroo/routing"
use "wallaroo/topology"
use "wallaroo/fail"

actor EmptySink is Consumer
  be run[D: Any val](metric_name: String, pipeline_time_spent: U64, data: D,
    origin: Producer, msg_uid: U128, frac_ids: FractionalMessageId,
    seq_id: SeqId, route_id: RouteId,
    latest_ts: U64, metrics_id: U16, worker_ingress_ts: U64)
  =>
    ifdef "trace" then
      @printf[I32]("Rcvd msg at EmptySink\n".cstring())
    end
    None

  be replay_run[D: Any val](metric_name: String, pipeline_time_spent: U64,
    data: D, origin: Producer, msg_uid: U128, frac_ids: FractionalMessageId,
    incoming_seq_id: SeqId, route_id: RouteId,
    latest_ts: U64, metrics_id: U16, worker_ingress_ts: U64)
  =>
    None

  be application_begin_reporting(initializer: LocalTopologyInitializer) =>
    initializer.report_created(this)

  be application_created(initializer: LocalTopologyInitializer,
    omni_router: OmniRouter)
  =>
    initializer.report_initialized(this)

  be application_initialized(initializer: LocalTopologyInitializer) =>
    initializer.report_ready_to_work(this)

  be application_ready_to_work(initializer: LocalTopologyInitializer) =>
    None

  be register_producer(producer: Producer) =>
    None

  be unregister_producer(producer: Producer) =>
    None

  be request_ack() =>
    None

  be receive_state(state: ByteSeq val) => Fail()
