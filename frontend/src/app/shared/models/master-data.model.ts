import { State } from './user.model';
export interface Client { id:number; document_type:string; document_number:string; business_name:string; contact_name?:string; phone?:string; email?:string; address?:string; state_id:number; state?:State; }
export interface Vehicle { id:number; client_id:number; plate:string; brand?:string; model?:string; color?:string; vehicle_type?:string; state_id:number; state?:State; client?:Client; }
export interface GpsDevice { id:number; vehicle_id:number; imei:string; serial_number?:string; model?:string; provider?:string; sim_number?:string; state_id:number; state?:State; vehicle?:Vehicle; }
export interface EventType { id:number; code:string; name:string; description?:string; default_priority:'critical'|'high'|'medium'|'low'; generates_alert:boolean; expected_action?:string; state_id:number; state?:State; }
export type MasterKind = 'clients'|'vehicles'|'gps-devices'|'event-types';
