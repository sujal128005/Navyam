std_msgs/Header header
string phase                 # IDLE, TAKEOFF, EXPLORE, RETURN, LAND, DONE, ABORTED
string reason                # why the last phase change happened
float32 elapsed_s            # since mission start
float32 battery_pct          # NaN if unknown
uint8 survivors_confirmed
uint8 survivors_expected
float32 explored_area_m2     # known cells in the SLAM map
