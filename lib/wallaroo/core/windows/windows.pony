/*

Copyright 2018 The Wallaroo Authors.

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
 implied. See the License for the specific language governing
 permissions and limitations under the License.

*/


use "buffered"
use "collections"
use "random"
use "serialise"
use "time"
use "wallaroo/core/aggregations"
use "wallaroo/core/common"
use "wallaroo/core/state"
use "wallaroo/core/topology"
use "wallaroo_labs/math"
use "wallaroo_labs/mort"

type WindowOutputs[Out: Any val] is (Array[(Out, U64)] val, U64, Bool)

primitive EmptyWindow
primitive EmptyPane

class RangeWindowsBuilder
  var _range: U64
  var _slide: U64
  var _delay: U64
  var _align_windows: Bool
  var _late_data_policy: U16 = LateDataPolicy.drop()

  new create(range: U64) =>
    _range = range
    _slide = range
    _delay = 0
    _align_windows = false

  fun ref with_slide(slide: U64): RangeWindowsBuilder =>
    _slide = slide
    this

  fun ref with_delay(delay: U64): RangeWindowsBuilder =>
    _delay = delay
    this

  fun ref unaligned() : RangeWindowsBuilder =>
    _align_windows = false
    this

  fun ref aligned() : RangeWindowsBuilder =>
    _align_windows = true
    this

  fun ref with_late_data_policy(p: U16): RangeWindowsBuilder =>
    _late_data_policy = p
    this

  fun ref over[In: Any val, Out: Any val, S: State ref](
    agg: Aggregation[In, Out, S]): StateInitializer[In, Out, S]
  =>
    if _slide > _range then
      FatalUserError("A window's slide cannot be greater than its range. " +
        "But found slide " + _slide.string() + " for range " + _range.string())
    end

    RangeWindowsStateInitializer[In, Out, S](agg, _range, _slide, _delay,
      _late_data_policy, _align_windows)

class EphemeralWindowsBuilder
  let _trigger_range: U64
  let _post_trigger_range: U64
  var _delay: U64
  var _late_data_policy: U16 = LateDataPolicy.drop()

  new create(trigger_range: U64, post_trigger_range: U64) =>
    _trigger_range = trigger_range
    _post_trigger_range = post_trigger_range
    _delay = 0

  fun ref with_delay(delay: U64): EphemeralWindowsBuilder =>
    _delay = delay
    this

  fun ref with_late_data_policy(p: U16): EphemeralWindowsBuilder =>
    _late_data_policy = p
    this

  fun ref over[In: Any val, Out: Any val, S: State ref](
    agg: Aggregation[In, Out, S]): StateInitializer[In, Out, S]
  =>
    EphemeralWindowsStateInitializer[In, Out, S](agg, _trigger_range,
      _post_trigger_range, _delay, _late_data_policy)

class CountWindowsBuilder
  var _count: USize

  new create(count: USize) =>
    _count = count

  fun ref over[In: Any val, Out: Any val, S: State ref](
    agg: Aggregation[In, Out, S]): StateInitializer[In, Out, S]
  =>
    TumblingCountWindowsStateInitializer[In, Out, S](agg, _count)

trait Windows[In: Any val, Out: Any val, Acc: State ref] is
  StateWrapper[In, Out, Acc]
  fun ref apply(input: In, event_ts: U64, watermark_ts: U64):
    (ComputationResult[Out], U64, Bool)

  fun ref on_timeout(input_watermark_ts: U64, output_watermark_ts: U64):
    (ComputationResult[Out], U64, Bool)

  fun ref flush_windows(input_watermark_ts: U64,
    output_watermark_ts: U64): (ComputationResult[Out], U64, Bool)

  /////////
  // _initial_* methods for windows that behave differently the first time
  // they encounter a watermark
  /////////
  fun ref _initial_apply(input: In, event_ts: U64, watermark_ts: U64,
    windows_wrapper: WindowsWrapper[In, Out, Acc]):
    (ComputationResult[Out], U64, Bool)
  =>
    (None, 0, true)

  fun ref _initial_attempt_to_trigger(input_watermark_ts: U64,
    windows_wrapper: WindowsWrapper[In, Out, Acc]):
    (ComputationResult[Out], U64, Bool)
  =>
    (None, 0, true)

trait WindowsWrapperBuilder[In: Any val, Out: Any val, Acc: State ref]
  fun ref apply(first_event_ts: U64, watermark_ts: U64):
    WindowsWrapper[In, Out, Acc]

trait WindowsWrapper[In: Any val, Out: Any val, Acc: State ref]
  fun ref apply(input: In, event_ts: U64, watermark_ts: U64):
    WindowOutputs[Out]

  fun ref attempt_to_trigger(watermark_ts: U64): WindowOutputs[Out]

  // !TODO! We should probably remove this.
  fun check_panes_increasing(): Bool =>
    false


///////////////////////////
// GLOBAL WINDOWS
///////////////////////////
class val GlobalWindowStateInitializer[In: Any val, Out: Any val,
  Acc: State ref] is StateInitializer[In, Out, Acc]
  let _agg: Aggregation[In, Out, Acc]

  new val create(agg: Aggregation[In, Out, Acc]) =>
    _agg = agg

  fun state_wrapper(key: Key, rand: Random): StateWrapper[In, Out, Acc] =>
    GlobalWindow[In, Out, Acc](key, _agg)

  fun val runner_builder(step_group_id: RoutingId, parallelism: USize,
    local_routing: Bool): RunnerBuilder
  =>
    StateRunnerBuilder[In, Out, Acc](this, step_group_id, parallelism,
      local_routing)

  fun timeout_interval(): U64 =>
    // Triggers on every message, so we don't need timeouts.
    0

  fun val decode(in_reader: Reader, auth: AmbientAuth):
    StateWrapper[In, Out, Acc] ?
  =>
    try
      let data: Array[U8] iso = in_reader.block(in_reader.size())?
      match Serialised.input(InputSerialisedAuth(auth), consume data)(
        DeserialiseAuth(auth))?
      | let gw: GlobalWindow[In, Out, Acc] => gw
      else
        error
      end
    else
      error
    end

  fun name(): String =>
    _agg.name()

class GlobalWindow[In: Any val, Out: Any val, Acc: State ref] is
  Windows[In, Out, Acc]
  let _key: Key
  let _agg: Aggregation[In, Out, Acc]
  let _acc: Acc

  new create(key: Key, agg: Aggregation[In, Out, Acc]) =>
    _key = key
    _agg = agg
    _acc = agg.initial_accumulator()

  fun ref apply(input: In, event_ts: U64, watermark_ts: U64):
    (ComputationResult[Out], U64, Bool)
  =>
    _agg.update(input, _acc)
    // We trigger a result per message
    let res = _agg.output(_key, event_ts, _acc)
    (res, watermark_ts, true)

  fun ref on_timeout(input_watermark_ts: U64, output_watermark_ts: U64):
    (ComputationResult[Out], U64, Bool)
  =>
    // We trigger per message, so we do nothing on the timer
    (recover val Array[Out] end, input_watermark_ts, true)

  fun ref flush_windows(input_watermark_ts: U64,
    output_watermark_ts: U64): (ComputationResult[Out], U64, Bool)
  =>
    // We trigger per message, so there is nothing to flush
    (recover val Array[Out] end, output_watermark_ts, true)

  fun ref encode(auth: AmbientAuth): ByteSeq =>
    try
      Serialised(SerialiseAuth(auth), this)?.output(OutputSerialisedAuth(
        auth))
    else
      Fail()
      recover Array[U8] end
    end

///////////////////////////
// RANGE WINDOWS
///////////////////////////
class val RangeWindowsStateInitializer[In: Any val, Out: Any val,
  Acc: State ref] is StateInitializer[In, Out, Acc]
  let _agg: Aggregation[In, Out, Acc]
  let _range: U64
  let _slide: U64
  let _delay: U64
  let _align_windows: Bool
  let _late_data_policy: U16

  new val create(agg: Aggregation[In, Out, Acc], range: U64, slide: U64,
    delay: U64, late_data_policy: U16, align_windows: Bool)
  =>
    if range == 0 then
      FatalUserError("Range windows must have a range greater than 0!\n")
    end
    if slide == 0 then
      FatalUserError("Range windows must have a slide greater than 0!\n")
    end
    _agg = agg
    _range = range
    _slide = slide
    _delay = delay
    _align_windows = align_windows
    _late_data_policy = late_data_policy

  fun state_wrapper(key: Key, rand: Random): StateWrapper[In, Out, Acc] =>
    // If the application will be using aligned windows, we must
    // ingore the provided Rand and supply Zeroes.
    let rand' = if _align_windows then _Zeroes else rand end
    let windows_wrapper_builder = _SlidingWindowsWrapperBuilder[In, Out, Acc](
      key, _agg, _range, _slide, _delay, rand', _late_data_policy)
    InitializableWindows[In, Out, Acc](windows_wrapper_builder)

  fun val runner_builder(step_group_id: RoutingId, parallelism: USize,
    local_routing: Bool): RunnerBuilder
  =>
    StateRunnerBuilder[In, Out, Acc](this, step_group_id, parallelism,
      local_routing)

  fun timeout_interval(): U64 =>
    // !TODO!: Decide if we should set a minimum to this interval to
    // avoid extremely frequent timer messages.
    (_range + _delay) * 2

  fun val decode(in_reader: Reader, auth: AmbientAuth):
    StateWrapper[In, Out, Acc] ?
  =>
    try
      let data: Array[U8] iso = in_reader.block(in_reader.size())?
      match Serialised.input(InputSerialisedAuth(auth), consume data)(
        DeserialiseAuth(auth))?
      | let iw: InitializableWindows[In, Out, Acc] => iw
      else
        error
      end
    else
      error
    end

  fun name(): String =>
    _agg.name()

class InitializableWindows[In: Any val, Out: Any val, Acc: State ref] is
  Windows[In, Out, Acc]
  """
  Used for windows types that need to go through an initialization phase in
  order to initialize windows using information from the first message received
  for a given key.
  """
  var _phase: WindowsPhase[In, Out, Acc] = EmptyWindowsPhase[In, Out, Acc]

  new create(wrapper_builder: WindowsWrapperBuilder[In, Out, Acc]) =>
    _phase = InitialWindowsPhase[In, Out, Acc](this, wrapper_builder)

  fun ref apply(input: In, event_ts: U64, watermark_ts: U64):
    (ComputationResult[Out], U64, Bool)
  =>
    _phase(input, event_ts, watermark_ts)

  fun ref _initial_apply(input: In, event_ts: U64, watermark_ts: U64,
    windows_wrapper: WindowsWrapper[In, Out, Acc]):
    (ComputationResult[Out], U64, Bool)
  =>
    _phase = ProcessingWindowsPhase[In, Out, Acc](windows_wrapper)
    _phase(input, event_ts, watermark_ts)

  fun ref on_timeout(input_watermark_ts: U64, output_watermark_ts: U64):
    (ComputationResult[Out], U64, Bool)
  =>
    _attempt_to_trigger(input_watermark_ts)

  fun ref flush_windows(input_watermark_ts: U64,
    output_watermark_ts: U64): (ComputationResult[Out], U64, Bool)
  =>
    _attempt_to_trigger(TimeoutWatermark())

  fun ref encode(auth: AmbientAuth): ByteSeq =>
    try
      Serialised(SerialiseAuth(auth), this)?.output(OutputSerialisedAuth(
        auth))
    else
      Fail()
      recover Array[U8] end
    end

  fun ref _attempt_to_trigger(input_watermark_ts: U64):
    (ComputationResult[Out], U64, Bool)
  =>
    _phase.attempt_to_trigger(input_watermark_ts)

  fun ref _initial_attempt_to_trigger(input_watermark_ts: U64,
    windows_wrapper: WindowsWrapper[In, Out, Acc]):
    (ComputationResult[Out], U64, Bool)
  =>
    _phase = ProcessingWindowsPhase[In, Out, Acc](windows_wrapper)
    _phase.attempt_to_trigger(input_watermark_ts)

  fun check_panes_increasing(): Bool =>
    _phase.check_panes_increasing()


////////////////////////////
// EPHEMERAL WINDOWS
////////////////////////////
class val EphemeralWindowsStateInitializer[In: Any val, Out: Any val,
  Acc: State ref] is StateInitializer[In, Out, Acc]
  let _agg: Aggregation[In, Out, Acc]
  let _trigger_range: U64
  let _post_trigger_range: U64
  let _delay: U64
  let _late_data_policy: U16

  new val create(agg: Aggregation[In, Out, Acc], trigger_range: U64,
    post_trigger_range: U64, delay: U64, late_data_policy: U16)
  =>
    if trigger_range == 0 then
      FatalUserError("Ephemeral windows must have a trigger range greater " +
        "than 0!")
    end
    _agg = agg
    _trigger_range = trigger_range
    _post_trigger_range = post_trigger_range
    _delay = delay
    _late_data_policy = late_data_policy

  fun state_wrapper(key: Key, rand: Random): StateWrapper[In, Out, Acc] =>
    // If the application will be using aligned windows, we must
    // ingore the provided Rand and supply Zeroes.
    let window_wrapper_builder = _EphemeralWindowWrapperBuilder[In, Out, Acc](
      key, _agg, _trigger_range, _post_trigger_range, _delay, rand,
      _late_data_policy)
    InitializableWindows[In, Out, Acc](window_wrapper_builder)

  fun val runner_builder(step_group_id: RoutingId, parallelism: USize,
    local_routing: Bool): RunnerBuilder
  =>
    StateRunnerBuilder[In, Out, Acc](this, step_group_id, parallelism,
      local_routing)

  fun timeout_interval(): U64 =>
    // !TODO!: Decide if we should set a minimum to this interval to
    // avoid extremely frequent timer messages.
    _trigger_range + _delay

  fun val decode(in_reader: Reader, auth: AmbientAuth):
    StateWrapper[In, Out, Acc] ?
  =>
    try
      let data: Array[U8] iso = in_reader.block(in_reader.size())?
      match Serialised.input(InputSerialisedAuth(auth), consume data)(
        DeserialiseAuth(auth))?
      | let iw: InitializableWindows[In, Out, Acc] => iw
      else
        error
      end
    else
      error
    end

  fun name(): String =>
    _agg.name()

////////////////////////////
// TUMBLING COUNT WINDOWS
////////////////////////////
class val TumblingCountWindowsStateInitializer[In: Any val, Out: Any val,
  Acc: State ref] is StateInitializer[In, Out, Acc]
  let _agg: Aggregation[In, Out, Acc]
  let _count: USize

  new val create(agg: Aggregation[In, Out, Acc], count: USize) =>
    _agg = agg
    _count = count

  fun state_wrapper(key: Key, rand: Random): StateWrapper[In, Out, Acc] =>
    TumblingCountWindows[In, Out, Acc](key, _agg, _count)

  fun val runner_builder(step_group_id: RoutingId, parallelism: USize,
    local_routing: Bool): RunnerBuilder
  =>
    StateRunnerBuilder[In, Out, Acc](this, step_group_id, parallelism,
      local_routing)

  fun timeout_interval(): U64 =>
    5_000_000_000

  fun val decode(in_reader: Reader, auth: AmbientAuth):
    StateWrapper[In, Out, Acc] ?
  =>
    try
      let data: Array[U8] iso = in_reader.block(in_reader.size())?
      match Serialised.input(InputSerialisedAuth(auth), consume data)(
        DeserialiseAuth(auth))?
      | let tw: TumblingCountWindows[In, Out, Acc] => tw
      else
        error
      end
    else
      error
    end

  fun name(): String =>
    _agg.name()

class TumblingCountWindows[In: Any val, Out: Any val, Acc: State ref] is
  Windows[In, Out, Acc]
  let _key: Key
  let _agg: Aggregation[In, Out, Acc]
  let _count_trigger: USize
  var _acc: Acc

  var _current_count: USize = 0

  new create(key: Key, agg: Aggregation[In, Out, Acc], count: USize) =>
    _key = key
    _agg = agg
    _count_trigger = count
    _acc = agg.initial_accumulator()

  fun ref apply(input: In, event_ts: U64, watermark_ts: U64):
    (ComputationResult[Out], U64, Bool)
  =>
    var out: (Out | None) = None
    _agg.update(input, _acc)
    _current_count = _current_count + 1

    if _current_count >= _count_trigger then
      out = _trigger(event_ts)
    end

    (out, watermark_ts, true)

  fun ref on_timeout(input_watermark_ts: U64, output_watermark_ts: U64):
    (ComputationResult[Out], U64, Bool)
  =>
    var out: (Out | None) = None
    var new_output_watermark_ts = output_watermark_ts
    if _current_count > 0 then
      out = _trigger(new_output_watermark_ts)
      new_output_watermark_ts = input_watermark_ts
    end
    (out, new_output_watermark_ts, true)

  fun ref flush_windows(input_watermark_ts: U64,
    output_watermark_ts: U64): (ComputationResult[Out], U64, Bool)
  =>
    var out: (Out | None) = None
    var new_output_watermark_ts = output_watermark_ts
    if _current_count > 0 then
      out = _trigger(new_output_watermark_ts)
      new_output_watermark_ts = input_watermark_ts
    end
    (out, new_output_watermark_ts, true)

  fun ref _trigger(output_watermark_ts: U64): (Out | None) =>
    var out: (Out | None) = None
    out = _agg.output(_key, output_watermark_ts, _acc)
    _acc = _agg.initial_accumulator()
    _current_count = 0
    out

  fun ref encode(auth: AmbientAuth): ByteSeq =>
    try
      Serialised(SerialiseAuth(auth), this)?.output(OutputSerialisedAuth(
        auth))
    else
      Fail()
      recover Array[U8] end
    end

class _Zeroes is Random
  new create(_: U64 = 0 , _: U64 = 0) => None
  fun ref next(): U64 => 0
