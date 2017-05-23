#ifndef __WALLAROO_SINK_ENCODER_H__
#define __WALLAROO_SINK_ENCODER_H__

#include <cstdlib>
#include "ManagedObject.hpp"
#include "Data.hpp"

namespace wallaroo
{
class SinkEncoder: public ManagedObject {
public:
  virtual size_t get_size(Data *data_) = 0;
  virtual void encode(Data *data_, char *bytes_) = 0;
};
}

#endif // __WALLAROO_SINK_ENCODER_H__