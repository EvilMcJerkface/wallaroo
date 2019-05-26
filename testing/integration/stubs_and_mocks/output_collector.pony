use "collections"
use "ponytest"
use "wallaroo/core/barrier"
use "wallaroo/core/checkpoint"
use "wallaroo/core/common"
use "wallaroo/core/initialization"
use "wallaroo/core/recovery"


actor TestOutputCollector[V: (Hashable & Equatable[V] & Stringable val)]
  is Consumer
  var _outputs: Array[String] = Array[String]
  let _h: TestHelper
  let _expected: Array[String] = Array[String]
  var _test_finished_msg: V

  new create(h: TestHelper, expected: Array[(V | BarrierToken)] val,
    test_finished_msg: V)
  =>
    _h = h
    for e in expected.values() do
      _expected.push(e.string())
    end
    _test_finished_msg = test_finished_msg

  fun ref process_test_output[D: Any val](d: (D | BarrierToken)) =>
    match d
    | let v: V =>
      if v == _test_finished_msg then
        check_results()
      else
        _outputs.push(v.string())
      end
    | let bt: BarrierToken =>
      _outputs.push(bt.string())
    else
      _h.fail("Invalid test output type!")
    end

  fun ref check_results() =>
    _h.assert_array_eq[String](_outputs, _expected)
    _h.complete(true)


  ///////////////////////
  // CONSUMER INTERFACE
  ///////////////////////
  be register_producer(id: RoutingId, producer: Producer) =>
    None

  be unregister_producer(id: RoutingId, producer: Producer) =>
    None

  be report_status(code: ReportStatusCode) =>
    None

  be run[D: Any val](metric_name: String, pipeline_time_spent: U64, data: D,
    key: Key, event_ts: U64, watermark_ts: U64, i_producer_id: RoutingId,
    i_producer: Producer, msg_uid: MsgId, frac_ids: FractionalMessageId,
    i_seq_id: SeqId, latest_ts: U64, metrics_id: U16, worker_ingress_ts: U64)
  =>
    process_test_output[D](data)

  be receive_barrier(step_id: RoutingId, producer: Producer,
    barrier_token: BarrierToken)
  =>
    process_test_output[V](barrier_token)

  fun ref process_message[D: Any val](metric_name: String,
    pipeline_time_spent: U64, data: D, key: Key, event_ts: U64,
    watermark_ts: U64, i_producer_id: RoutingId, i_producer: Producer,
    msg_uid: MsgId, frac_ids: FractionalMessageId, i_seq_id: SeqId,
    latest_ts: U64, metrics_id: U16, worker_ingress_ts: U64)
  =>
    None

  be request_ack() =>
    None

  be application_begin_reporting(initializer: LocalTopologyInitializer) =>
    None

  be application_created(initializer: LocalTopologyInitializer) =>
    None

  be application_initialized(initializer: LocalTopologyInitializer) =>
    None

  be application_ready_to_work(initializer: LocalTopologyInitializer) =>
    None

  be cluster_ready_to_work(initializer: LocalTopologyInitializer) =>
    None

  fun ref barrier_complete(barrier_token: BarrierToken) =>
    None

  fun ref checkpoint_state(checkpoint_id: CheckpointId) =>
    None

  be prepare_for_rollback() =>
    None

  be rollback(payload: ByteSeq val, event_log: EventLog,
    checkpoint_id: CheckpointId)
  =>
    None