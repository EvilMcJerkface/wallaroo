/*

Copyright 2017 The Wallaroo Authors.

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

use "options"
use "wallaroo"
use "wallaroo/core/partitioning"
use "wallaroo/core/source"

class val GenSourceConfig[In: Any val] is SourceConfig
  let _worker_source_config: WorkerGenSourceConfig[In]

  new val create(gen: GenSourceGeneratorBuilder[In]) =>
    _worker_source_config = WorkerGenSourceConfig[In](gen)

  fun val source_coordinator_builder_builder(): GenSourceCoordinatorBuilderBuilder[In] =>
    GenSourceCoordinatorBuilderBuilder[In]

  fun default_partitioner_builder(): PartitionerBuilder =>
    PassthroughPartitionerBuilder

  fun worker_source_config(): WorkerSourceConfig =>
    _worker_source_config

class val WorkerGenSourceConfig[In: Any val] is WorkerSourceConfig
  let generator: GenSourceGeneratorBuilder[In]

  new val create(generator': GenSourceGeneratorBuilder[In]) =>
    generator = generator'
