# A confirmed survivor, as shown on the GCS map.
uint32 id
geometry_msgs/Point position        # map frame
string grid_label                   # e.g. "C4"; empty if outside the arena grid
int32 grid_col                      # -1 if outside
int32 grid_row                      # -1 if outside
float32 confidence                  # best detector confidence seen
uint32 hits                         # detections merged into this survivor
builtin_interfaces/Time confirmed_at
