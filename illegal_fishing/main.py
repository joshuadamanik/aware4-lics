import numpy as np
import rclpy
from rclpy.node import Node
from px4_msgs.msg import VehicleCommand, VehicleCommandAck, HomePosition, VehicleStatus, VehicleOdometry, VehicleGpsPosition
import time
import sys
import math
import logging
logging.basicConfig(level=logging.INFO)


def xy2latlon(dx, dy, dz=None):
    new_lat = 1. * 43.81678595809796 + (dy / 6378000) * (180 / math.pi)
    new_lon = 1. * 28.581366799068558 + (dx / 6378000) * (180 / math.pi) / math.cos(43.81678595809796 * math.pi / 180)
    if dz is None:
        return new_lat, new_lon
    else:
        return new_lat, new_lon, dz


class Vehicle():
    MODE_INIT = 0
    MODE_STANDBY = 1
    MODE_ARMED = 2
    MODE_TAKEOFF = 3
    MODE_LOITER = 4
    MODE_MOVING = 5

    def __init__(self, node, id, flight_alt:float =10.):
        self.id = id
        self.node = node
        self.pos = None
        self.home = None
        self.logger = logging.getLogger('agent%d' % id)
        self.ready = False
        self.nav_state = None
        self.arming_state = None
        self.vehicle_type = None
        self.mode = self.MODE_INIT
        self.waypoint = None

        self.flight_alt = flight_alt
        self.command = self.node.create_publisher(VehicleCommand, '/vehicle%d/in/VehicleCommand' % id, 10)
        self.command_sub = self.node.create_subscription(VehicleCommandAck, '/vehicle%d/out/VehicleCommandAck' % id, self.on_command_callback, 10)
        self.status_sub = self.node.create_subscription(VehicleStatus, '/vehicle%d/out/VehicleStatus' % id, self.on_status_callback, 10)
        self.gps_sub = self.node.create_subscription(VehicleGpsPosition, '/vehicle%d/out/VehicleGpsPosition' % id, self.on_gps_callback, 10)

        self.init_pos = []

    def on_home_callback(self, msg):
        # print(msg)
        pass

    def on_command_callback(self, msg):
        self.logger.debug(msg)


    def on_status_callback(self, msg):
        self.nav_state = msg.nav_state
        self.arming_state = msg.arming_state
        self.vehicle_type = msg.vehicle_type

        if self.mode == self.MODE_STANDBY:
            if self.arming_state == 2:
                self.mode = self.MODE_ARMED
            else:
                self.arm()
        if self.mode == self.MODE_ARMED:
            if self.nav_state == 17:
                self.mode = self.MODE_TAKEOFF
            elif self.nav_state == 4 and abs(self.pos[2] - self.flight_alt) < 0.5:
                self.mode = self.MODE_LOITER
            else:
                self.takeoff()
        if self.mode == self.MODE_TAKEOFF:
            if self.nav_state == 4:
                self.mode = self.MODE_LOITER
            elif self.nav_state == 5:
                self.mode = self.MODE_STANDBY
        if self.mode == self.MODE_LOITER:
            if self.waypoint:
                self.set_position(self.waypoint)
                self.mode = self.MODE_MOVING

        self.logger.debug('nav_state: %d, arming_state: %d, mode: %d' % (self.nav_state, self.arming_state, self.mode))

    def move(self, x, y):
        self.waypoint = xy2latlon(x, y, self.flight_alt)

    def on_gps_callback(self, msg):
        coor = [msg.lat * 1e-7, msg.lon * 1e-7, msg.alt * 1e-3]
        if self.home is None:
            self.init_pos.append(coor)
            if len(self.init_pos) >= 10:
                self.home = np.average(self.init_pos, axis=0).tolist()
                del self.init_pos
                self.mode = self.MODE_STANDBY

        self.pos = coor
        if self.mode == self.MODE_MOVING:
            dist = np.sqrt((self.waypoint[0] - self.pos[0]) ** 2 + (self.waypoint[1] - self.pos[1]) ** 2)
            self.logger.debug('Distance to waypoint: %.4f' % dist)
            if dist < 1e-5:
                self.mode = self.MODE_LOITER
                self.waypoint = None

        self.logger.debug('Received GPS coordinate: [%.4f, %.4f, %.4f]' % tuple(self.pos))

        # if self.mode == self.MODE_READY:
        #     if abs(self.location[2] - self.flight_alt) > 0.5:
        #         self.set_position((self.location[0], self.location[1], self.flight_alt))
        # pass

    def arm(self):
        self.logger.info("send ARM command")
        arm_cmd = VehicleCommand()
        arm_cmd.target_system = self.id
        arm_cmd.command = 400
        arm_cmd.param1 = 1.0
        arm_cmd.confirmation = True
        arm_cmd.from_external = True
        self.command.publish(arm_cmd)

    def disarm(self):
        self.logger.info("send DISARM command")
        disarm_cmd = VehicleCommand()
        disarm_cmd.target_system = self.id
        disarm_cmd.command = 400
        disarm_cmd.param1 = 0.0
        disarm_cmd.confirmation = True
        disarm_cmd.from_external = True
        self.command.publish(disarm_cmd)

    def takeoff(self, pos=None, flight_alt=None):
        if not pos:
            pos = self.pos
        if not flight_alt:
            flight_alt = self.flight_alt
        self.logger.info("send Takeoff command")
        takeoff_cmd = VehicleCommand()
        takeoff_cmd.target_system = self.id
        takeoff_cmd.command = 22
        takeoff_cmd.param1 = 0.0
        takeoff_cmd.param5 = pos[0]
        takeoff_cmd.param6 = pos[1]
        takeoff_cmd.param7 = flight_alt
        takeoff_cmd.confirmation = True
        takeoff_cmd.from_external = True
        self.command.publish(takeoff_cmd)

    def land(self):
        self.logger.info("send landing command")
        landing_cmd = VehicleCommand()
        landing_cmd.target_system = self.id
        landing_cmd.command = 21
        landing_cmd.from_external = True
        self.command.publish(landing_cmd)

    def set_position(self, waypoint):
        self.logger.info("send moving command")
        move_cmd = VehicleCommand()
        move_cmd.target_system = self.id
        move_cmd.command = 192
        move_cmd.param1 = -1.0
        move_cmd.param2 = 1.0
        move_cmd.param3 = 0.0
        move_cmd.param4 = float('nan')
        move_cmd.param5 = waypoint[0]
        move_cmd.param6 = waypoint[1]
        move_cmd.param7 = waypoint[2]
        move_cmd.confirmation = True
        move_cmd.from_external = True
        self.command.publish(move_cmd)

    def set_mode(self, mode=0):
        self.logger.info("send SET MODE command")
        msg = VehicleCommand()
        msg.target_system = self.id
        msg.command = 176
        msg.param1 = float(mode)
        msg.confirmation = True
        msg.from_external = True
        self.command.publish(msg)

def main(args=None):
    start_time = time.time()
    rclpy.init(args=args)

    node = Node('px4_command_publisher')

    num_vehicles = 3

    vehicles = [Vehicle(node, i, 7.) for i in range(1, num_vehicles+1)]

    waypoints = np.genfromtxt('/root/scenario/waypoint1.csv', delimiter=',')
    step = 0
    max_steps = len(waypoints)

    exit_value = 0
    waypoints_ready = True
    # rclpy.spin(scenario_test)
    while rclpy.ok():
        rclpy.spin_once(node)
        # time.sleep(0.1)
        cur_time = time.time()

        all_loiter = True
        for vehicle in vehicles:
            if vehicle.mode != vehicle.MODE_LOITER:
                all_loiter = False
                break

        if all_loiter:
            if waypoints_ready:
                if step == max_steps:
                    break
                print('Step %d' % step)
                for i, vehicle in enumerate(vehicles):
                    vehicle.move(waypoints[step][2*i] * 2 - 100, waypoints[step][2*i+1] * 2 - 100)
                step += 1
                waypoints_ready = False
        else:
            waypoints_ready = True

    rclpy.shutdown()

    if exit_value == 0:
        print("SCENARIO PASS")
        exit(0)
    else:
        print("SCENARIO FAIL")
        exit(1)


if __name__ == '__main__':
    print(main())
